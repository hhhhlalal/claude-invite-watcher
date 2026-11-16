"""Railway worker and protected dashboard. Import has no filesystem/env side effects."""
import base64
import hmac
import json
import logging
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import watcher
from sessions import SessionStore


def load_config():
    cfg = json.loads(Path(__file__).with_name('config.json').read_text(encoding='utf-8-sig'))
    if not isinstance(cfg.get('queries'), list) or not 1 <= len(cfg['queries']) <= 10 or not all(isinstance(q, str) and q.strip() for q in cfg['queries']):
        raise ValueError('config.json: queries must contain 1-10 non-empty strings')
    for name, low, high in [('interval_seconds', 120, 86400), ('scroll_pages', 1, 10), ('max_age_hours', 1, 168)]:
        if not isinstance(cfg.get(name), (int, float)) or not low <= cfg[name] <= high:
            raise ValueError('config.json: invalid ' + name)
    if not isinstance(cfg['scroll_pages'], int):
        raise ValueError('scroll_pages must be an integer')
    cfg['ntfy_topic'] = os.getenv('NTFY_TOPIC', '').strip()
    cfg['ntfy_server'] = os.getenv('NTFY_SERVER', 'https://ntfy.sh').strip()
    target = urlsplit(cfg['ntfy_server'])
    if target.scheme != 'https' or not target.hostname or target.username or target.password or target.query or target.fragment:
        raise ValueError('NTFY_SERVER must be an HTTPS server URL without credentials or query')
    return cfg


class Runtime:
    def __init__(self, directory, cfg, password):
        self.directory = Path(directory)
        self.cfg = cfg
        self.password = password
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.worker = None
        self.deadline = time.monotonic() + 900
        self.last_alert = None
        self.alert_at = 0
        self.status = dict(state='starting', last_cycle=None, last_success=None,
                           successful_queries=0, pending_notifications=0,
                           notification_failures=0, last_error=None, next_run_at=None)

    def update(self, **values):
        with self.lock:
            self.status.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def healthy(self):
        return bool(self.worker and self.worker.is_alive() and time.monotonic() < self.deadline)

    def wait(self, seconds):
        self.deadline = time.monotonic() + seconds + 900
        self.update(next_run_at=time.time() + seconds)
        self.stop.wait(seconds)

    def alert(self, code):
        if code == self.last_alert and time.monotonic() - self.alert_at < 3600:
            return
        if not self.cfg['ntfy_topic']:
            return
        try:
            watcher.send_push(self.cfg, 'Watcher needs attention: ' + code + '\nOpen the protected /status page.', 'Claude watcher status')
            self.last_alert, self.alert_at = code, time.monotonic()
        except Exception:
            logging.warning('Status notification failed; will retry later')

    def scan_cycle(self, db):
        from playwright.sync_api import sync_playwright
        sessions = SessionStore(self.directory)
        state = sessions.load(os.environ['X_STORAGE_STATE_B64'])
        success, errors = 0, []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=state, viewport={'width': 1280, 'height': 900})
                page = context.new_page()
                self.update(notification_failures=0)
                for query in self.cfg['queries']:
                    if self.stop.is_set():
                        break
                    try:
                        for post in watcher.scan(page, query, self.cfg):
                            watcher.save(db, post)
                        success += 1
                    except Exception as error:
                        code = error.code if isinstance(error, watcher.ScanError) else type(error).__name__
                        errors.append(code)
                        logging.warning('Search query failed: %s', code)
                    watcher.report(db)
                    delivery = watcher.notify_pending(db, self.cfg)
                    self.update(notification_failures=delivery['failed'])
                if success:
                    sessions.save(context.storage_state())
                self.update(pending_notifications=db.execute('SELECT COUNT(*) FROM hits WHERE sent=0').fetchone()[0])
            finally:
                browser.close()
        values = dict(successful_queries=success, last_cycle=time.time(), last_error=', '.join(sorted(set(errors))) or None)
        if success:
            values['last_success'] = time.time()
        code = 'waiting' if success == len(self.cfg['queries']) else ('partial_failure' if success else 'X_unavailable_check_session')
        self.update(state=code, **values)
        if errors:
            self.alert(code)
        else:
            self.last_alert = None

    def run(self):
        db = None
        try:
            db = watcher.database(self.directory / 'state.db')
            watcher.report(db)
            while not self.stop.is_set():
                self.deadline = time.monotonic() + 900 + 300 * len(self.cfg['queries'])
                if not self.cfg['ntfy_topic']:
                    self.update(state='waiting_for_NTFY_TOPIC')
                    self.wait(30)
                    continue
                delivery = watcher.notify_pending(db, self.cfg)
                self.update(notification_failures=delivery['failed'], pending_notifications=db.execute('SELECT COUNT(*) FROM hits WHERE sent=0').fetchone()[0])
                if not os.getenv('X_STORAGE_STATE_B64'):
                    self.update(state='waiting_for_X_STORAGE_STATE_B64')
                    self.alert('waiting_for_X_STORAGE_STATE_B64')
                    self.wait(30)
                    continue
                try:
                    self.update(state='scanning', next_run_at=None)
                    self.scan_cycle(db)
                except ValueError:
                    self.update(state='invalid_X_session', last_error='Export the X session again; check X_STORAGE_STATE_B64')
                    self.alert('invalid_X_session')
                except Exception as error:
                    self.update(state='error_' + type(error).__name__, last_error=type(error).__name__)
                    logging.error('Cycle failed: %s', type(error).__name__)
                    self.alert('scan_error')
                delay = self.cfg['interval_seconds'] if self.snapshot()['state'] == 'waiting' else max(600, self.cfg['interval_seconds'])
                self.wait(delay)
        finally:
            if db is not None:
                db.close()


def make_server(runtime, host='0.0.0.0', port=8080):
    expected = ('Basic ' + base64.b64encode(('admin:' + runtime.password).encode()).decode()).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/health':
                healthy = runtime.healthy()
                self.respond(200 if healthy else 503, b'ok' if healthy else b'worker stopped or stalled', 'text/plain')
                return
            actual = self.headers.get('Authorization', '').encode('utf-8')
            if not hmac.compare_digest(actual, expected):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="Invite Watcher", charset="UTF-8"')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if path in ('/status', '/ready'):
                status = runtime.snapshot()
                ready = runtime.healthy() and status['state'] == 'waiting' and not status['pending_notifications']
                self.respond(503 if path == '/ready' and not ready else 200, json.dumps(status).encode(), 'application/json')
            elif path in ('/', '/results'):
                output = runtime.directory / 'results.html'
                body = output.read_bytes() if output.exists() else b'<h1>Waiting for first scan</h1><a href="/status">Status</a>'
                self.respond(200, body, 'text/html; charset=utf-8')
            else:
                self.respond(404, b'Not found', 'text/plain')

        def respond(self, code, body, kind):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main():
    logging.basicConfig(level=logging.INFO)
    password = os.getenv('DASHBOARD_PASSWORD', '')
    if len(password) < 20:
        raise SystemExit('Set DASHBOARD_PASSWORD to at least 20 characters.')
    directory = Path(os.getenv('DATA_DIR', '/data'))
    directory.mkdir(parents=True, exist_ok=True)
    watcher.ROOT = directory
    runtime = Runtime(directory, load_config(), password)
    runtime.worker = threading.Thread(target=runtime.run, daemon=True, name='watcher')
    server = make_server(runtime, port=int(os.getenv('PORT', '8080')))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: runtime.stop.set())
    runtime.worker.start()
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        while not runtime.stop.wait(2):
            if not runtime.healthy():
                raise SystemExit('Worker stopped or stalled; exiting so Railway can restart the service')
    finally:
        runtime.stop.set()
        server.shutdown()
        server.server_close()
        runtime.worker.join(timeout=5)


if __name__ == '__main__':
    main()
