import base64, hmac, json, logging, os, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import watcher

DATA=Path(os.getenv('DATA_DIR','/data')); DATA.mkdir(parents=True, exist_ok=True)
watcher.ROOT=DATA
PASSWORD=os.environ.get('DASHBOARD_PASSWORD','')
if len(PASSWORD)<20: raise SystemExit('Set DASHBOARD_PASSWORD to at least 20 characters.')
STATUS={'state':'starting','last_cycle':None,'successful_queries':0}

def run():
    from playwright.sync_api import sync_playwright
    cfg=json.loads(Path(__file__).with_name('config.json').read_text())
    cfg['ntfy_topic']=os.getenv('NTFY_TOPIC','')
    cfg['ntfy_server']=os.getenv('NTFY_SERVER','https://ntfy.sh')
    db=watcher.database(DATA/'state.db')
    while True:
        try:
            raw=os.getenv('X_STORAGE_STATE_B64','')
            if not raw:
                STATUS['state']='waiting_for_X_STORAGE_STATE_B64'; time.sleep(30); continue
            if not cfg['ntfy_topic']:
                STATUS['state']='waiting_for_NTFY_TOPIC'; time.sleep(30); continue
            state=json.loads(base64.b64decode(raw, validate=True))
            success=0
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                try:
                    context=browser.new_context(storage_state=state,viewport={'width':1280,'height':900})
                    page=context.new_page()
                    STATUS['state']='scanning'
                    for query in cfg['queries']:
                        try:
                            for post in watcher.scan(page,query,cfg): watcher.save(db,post)
                            success+=1
                        except Exception as e:
                            logging.warning('Query unavailable: %s',type(e).__name__)
                    watcher.report(db); watcher.notify_pending(db,cfg)
                finally: browser.close()
            STATUS.update(state='waiting' if success else 'X_unavailable_check_session',last_cycle=time.time(),successful_queries=success)
        except Exception as e:
            STATUS['state']='error_'+type(e).__name__
            logging.exception('Cycle failed')
        time.sleep(300 if STATUS['state']=='waiting' else 600)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/health':
            self.send_response(200 if worker.is_alive() else 503); self.end_headers(); self.wfile.write(b'ok' if worker.is_alive() else b'worker stopped'); return
        expected='Basic '+base64.b64encode(('admin:'+PASSWORD).encode()).decode()
        if not hmac.compare_digest(self.headers.get('Authorization',''),expected):
            self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="Invite Watcher"'); self.end_headers(); return
        if self.path=='/status':
            body=json.dumps(STATUS).encode(); kind='application/json'
        elif self.path in ('/','/results'):
            path=DATA/'results.html'
            body=path.read_bytes() if path.exists() else b'<h1>Waiting for first scan</h1><a href="/status">Status</a>'
            kind='text/html; charset=utf-8'
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type',kind); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    worker=threading.Thread(target=run,daemon=True); worker.start()
    ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
