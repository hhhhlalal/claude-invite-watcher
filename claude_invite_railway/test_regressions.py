import base64
import datetime as dt
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import requests
import server
import sessions
import watcher


def fake_state(value='test-token'):
    return {'cookies':[{'name':'auth_token','value':value,'domain':'.x.com','path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'None'}], 'origins':[]}


def encoded(state):
    return base64.b64encode(json.dumps(state).encode()).decode()


def post(links=None):
    return dict(invites=links or ['https://claude.ai/duet-invite/test'], post_url='https://x.com/test/status/123',
                text='<script>alert(1)</script>', kind='invite', published='2026-11-16T00:00:00Z')


class FilteringTests(unittest.TestCase):
    def test_seven_day_boundary(self):
        for days in (17, 27, 70):
            self.assertIsNone(watcher.classify(f'Claude {days} days free trial invite', [])[0])
        self.assertIsNotNone(watcher.classify('Claude 7 ngày dùng thử', [])[0])

    def test_preserve_invite_query(self):
        self.assertEqual(watcher.invite('https://claude.ai/duet-invite/?code=A&amp;x=1'), 'https://claude.ai/duet-invite/?code=A&x=1')

    def test_reject_control_and_truncated_url(self):
        for url in ('https://claude.ai/duet-invite/a\nb', 'https://claude.ai/duet-invite/abc…'):
            self.assertIsNone(watcher.invite(url))

    def test_bad_row_does_not_abort_scan(self):
        cfg={'max_age_hours':24}
        row={'post':'https://x.com/test/status/123','time':'invalid','text':'test','urls':[]}
        self.assertIsNone(watcher.row_to_post(row,cfg,{}))
        row['time']=dt.datetime.now(dt.timezone.utc).isoformat()
        row['urls']=['https://[bad-host']
        self.assertIsNone(watcher.row_to_post(row,cfg,{}))

    def test_old_future_and_naive_dates_are_rejected(self):
        for value in (dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=2), dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=2), dt.datetime.now()):
            row={'post':'https://x.com/test/status/123','time':value.isoformat(),'text':'Claude','urls':['https://claude.ai/duet-invite/test']}
            self.assertIsNone(watcher.row_to_post(row,{'max_age_hours':24},{}))

    def test_visible_url_and_canonical_post(self):
        row={'post':'https://twitter.com/test/status/123','time':dt.datetime.now(dt.timezone.utc).isoformat(),'text':'Sharing','urls':['claude.ai/duet-invite/abc']}
        result=watcher.row_to_post(row,{'max_age_hours':24},{})
        self.assertEqual(result['invites'],['https://claude.ai/duet-invite/abc'])
        self.assertEqual(result['post_url'],'https://x.com/test/status/123')

    def test_short_url_only_contacts_tco_once(self):
        cache={}
        with patch('requests.get') as get:
            response=get.return_value.__enter__.return_value
            response.status_code=302
            response.headers={'Location':'https://claude.ai/duet-invite/abc'}
            self.assertIsNone(watcher.resolve_short_url('https://example.com/a',cache))
            for _ in range(2):
                self.assertEqual(watcher.resolve_short_url('https://t.co/test',cache),'https://claude.ai/duet-invite/abc')
            self.assertEqual(get.call_count,1)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])


class SessionTests(unittest.TestCase):
    def test_invalid_session(self):
        for raw in ('bad-base64', encoded([]), encoded({'cookies': []})):
            with self.assertRaises(ValueError): sessions.decode_state(raw)

    def test_drop_other_site_data(self):
        state=fake_state()
        state['cookies'].append({'name':'secret','value':'never-save','domain':'example.com'})
        state['origins']=[{'origin':'https://example.com','localStorage':[]}]
        self.assertEqual(sessions.decode_state(encoded(state)),fake_state())

    def test_expired_session_rejected(self):
        state=fake_state(); state['cookies'][0]['expires']=time.time()-30
        with self.assertRaises(ValueError): sessions.validate_state(state)

    def test_refreshed_cookie_survives_and_new_seed_replaces(self):
        with tempfile.TemporaryDirectory() as directory:
            store=sessions.SessionStore(directory)
            store.load(encoded(fake_state()))
            store.save(fake_state('refreshed'))
            self.assertEqual(store.load(encoded(fake_state())),fake_state('refreshed'))
            self.assertEqual(store.load(encoded(fake_state('new-login'))),fake_state('new-login'))
            if os.name!='nt': self.assertEqual(store.state_path.stat().st_mode & 0o777,0o600)


class OutboxTests(unittest.TestCase):
    def setUp(self): self.db=watcher.database(':memory:')
    def tearDown(self): self.db.close()

    def test_failed_delivery_retained_and_retry_deduped(self):
        watcher.save(self.db,post())
        with patch.object(watcher,'send_push',side_effect=requests.Timeout):
            self.assertEqual(watcher.notify_pending(self.db,{'ntfy_topic':'test'})['failed'],1)
        self.assertEqual(self.db.execute('SELECT sent FROM hits').fetchone()[0],0)
        with patch.object(watcher,'send_push') as send:
            watcher.notify_pending(self.db,{'ntfy_topic':'test'})
            watcher.notify_pending(self.db,{'ntfy_topic':'test'})
            send.assert_called_once()
        self.assertEqual(self.db.execute('SELECT sent FROM hits').fetchone()[0],1)

    def test_one_post_with_two_invites_sends_one_notification(self):
        watcher.save(self.db,post(['https://claude.ai/duet-invite/1','https://claude.ai/duet-invite/2']))
        with patch.object(watcher,'send_push') as send:
            watcher.notify_pending(self.db,{'ntfy_topic':'test'})
            send.assert_called_once()
        self.assertEqual(self.db.execute('SELECT SUM(sent) FROM hits').fetchone()[0],2)

    def test_desktop_failure_does_not_discard_notification(self):
        watcher.save(self.db,post())
        with patch.dict('sys.modules',{'plyer':None}):
            self.assertEqual(watcher.notify_pending(self.db,{})['failed'],1)
        self.assertEqual(self.db.execute('SELECT sent FROM hits').fetchone()[0],0)

    def test_report_escapes_post_text(self):
        watcher.save(self.db,post())
        with tempfile.TemporaryDirectory() as directory,patch.object(watcher,'ROOT',Path(directory)):
            watcher.report(self.db)
            output=(Path(directory)/'results.html').read_text()
            self.assertIn('&lt;script&gt;',output)
            self.assertNotIn('<script>',output)
            self.assertFalse((Path(directory)/'results.html.tmp').exists())

    def test_ntfy_real_http_accept_and_redirect_rejection(self):
        received=[]
        class MockNtfy(BaseHTTPRequestHandler):
            response=200
            def do_POST(self):
                received.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(self.response); self.end_headers()
            def log_message(self,*args): pass
        http=ThreadingHTTPServer(('127.0.0.1',0),MockNtfy)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            cfg={'ntfy_topic':'local-test','ntfy_server':f'http://127.0.0.1:{http.server_port}'}
            watcher.send_push(cfg,'Thông báo thử nghiệm')
            self.assertEqual(received[0].decode(),'Thông báo thử nghiệm')
            MockNtfy.response=302
            with self.assertRaises(requests.HTTPError): watcher.send_push(cfg,'test')
        finally:
            http.shutdown();http.server_close();thread.join()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.runtime=server.Runtime(self.temp.name,{'ntfy_topic':'test'},'test-password-at-least-20')
        self.alive=threading.Event()
        self.runtime.worker=threading.Thread(target=self.alive.wait,daemon=True)
        self.runtime.worker.start()
        self.http=server.make_server(self.runtime,'127.0.0.1',0)
        self.serving=threading.Thread(target=self.http.serve_forever,daemon=True);self.serving.start()
        self.url=f'http://127.0.0.1:{self.http.server_port}'
        self.auth=('admin',self.runtime.password)
    def tearDown(self):
        self.alive.set();self.runtime.worker.join()
        self.http.shutdown();self.http.server_close();self.serving.join();self.temp.cleanup()

    def test_auth_required_and_invalid_auth_does_not_crash(self):
        for route in ('/','/results','/status','/ready','/session-state.json'):
            self.assertEqual(requests.get(self.url+route,timeout=3).status_code,401)
        self.assertEqual(requests.get(self.url+'/status',headers={'Authorization':'invalid'},timeout=3).status_code,401)
        response=requests.get(self.url+'/status',auth=self.auth,timeout=3)
        self.assertEqual(response.status_code,200)
        self.assertNotIn(self.runtime.password,response.text)
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_health_and_ready_are_distinct(self):
        self.assertEqual(requests.get(self.url+'/health',timeout=3).status_code,200)
        self.assertEqual(requests.get(self.url+'/ready',auth=self.auth,timeout=3).status_code,503)
        self.runtime.update(state='waiting',last_success=time.time())
        self.assertEqual(requests.get(self.url+'/ready',auth=self.auth,timeout=3).status_code,200)
        self.runtime.update(pending_notifications=1)
        self.assertEqual(requests.get(self.url+'/ready',auth=self.auth,timeout=3).status_code,503)
        self.runtime.deadline=time.monotonic()-1
        self.assertEqual(requests.get(self.url+'/health',timeout=3).status_code,503)

    def test_sensitive_files_not_served(self):
        (Path(self.temp.name)/'session-state.json').write_text('PRIVATE')
        self.assertEqual(requests.get(self.url+'/session-state.json',auth=self.auth,timeout=3).status_code,404)

    def test_health_worker_dead(self):
        self.alive.set();self.runtime.worker.join()
        self.assertEqual(requests.get(self.url+'/health',timeout=3).status_code,503)

    def test_alert_dedup_and_failed_send_retry(self):
        with patch.object(watcher,'send_push') as send:
            self.runtime.alert('login_required');self.runtime.alert('login_required')
            send.assert_called_once()
        with patch.object(watcher,'send_push',side_effect=requests.Timeout) as send:
            self.runtime.alert('new_error');self.runtime.alert('new_error')
            self.assertEqual(send.call_count,2)


class RuntimeTests(unittest.TestCase):
    def test_success_and_partial_failure_with_engine_stub(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(watcher,'ROOT',Path(directory)), patch.dict(os.environ,{'X_STORAGE_STATE_B64':encoded(fake_state())}), patch('playwright.sync_api.sync_playwright') as engine, patch.object(watcher,'scan') as scan, patch.object(watcher,'send_push'):
            context=engine.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.storage_state.return_value=fake_state('renewed')
            runtime=server.Runtime(directory,{'queries':['one','two'],'ntfy_topic':'test'},'test-password-at-least-20')
            db=watcher.database(':memory:')
            try:
                scan.side_effect=[[],[]]
                runtime.scan_cycle(db)
                self.assertEqual(runtime.snapshot()['state'],'waiting')
                self.assertEqual(runtime.snapshot()['successful_queries'],2)
                self.assertEqual(sessions.SessionStore(directory).load(encoded(fake_state())),fake_state('renewed'))
                scan.side_effect=[[],watcher.ScanError('login_required')]
                runtime.scan_cycle(db)
                self.assertEqual(runtime.snapshot()['state'],'partial_failure')
                self.assertEqual(runtime.snapshot()['last_error'],'login_required')
            finally: db.close()

    def test_saved_refreshed_session_outlives_initial_import(self):
        with tempfile.TemporaryDirectory() as directory:
            state=fake_state();state['cookies'][0]['expires']=time.time()+60
            store=sessions.SessionStore(directory)
            store.load(encoded(state))
            store.save(fake_state('fresh'))
            with patch('sessions.time.time',return_value=time.time()+120):
                self.assertEqual(store.load(encoded(state)),fake_state('fresh'))

if __name__=='__main__': unittest.main()
