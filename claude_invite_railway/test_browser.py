"""Real Chromium against intercepted local fixture pages, never an X account."""
import datetime as dt
import os
import unittest
from unittest.mock import patch
import watcher


@unittest.skipUnless(os.getenv('RUN_BROWSER_TESTS')=='1','Set RUN_BROWSER_TESTS=1 after installing Chromium')
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw=sync_playwright().start()
        options={'headless':True}
        if os.getenv('TEST_BROWSER_EXECUTABLE'): options['executable_path']=os.environ['TEST_BROWSER_EXECUTABLE']
        try:
            cls.browser=cls.pw.chromium.launch(**options)
        except Exception:
            cls.pw.stop()
            raise
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context()
        self.page=self.context.new_page()
        self.cfg={'scroll_pages':1,'max_age_hours':24,'results_timeout_ms':500}
    def tearDown(self): self.context.close()
    def html(self,body):
        self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=body))
    def test_real_dom_article_extracts_invite_and_skips_bad_time(self):
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        body=f'''<article data-testid="tweet"><a href="https://x.com/a/status/100"><time datetime="{now}"></time></a><div data-testid="tweetText">Sharing a link</div><a href="https://claude.ai/duet-invite/ABC?code=1">invite</a></article>
        <article data-testid="tweet"><a href="https://x.com/a/status/101"><time datetime="bad"></time></a><div data-testid="tweetText">Claude 7 days free</div></article>'''
        self.html(body)
        hits=watcher.scan(self.page,'test',self.cfg)
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['invites'],['https://claude.ai/duet-invite/ABC?code=1'])
    def test_explicit_no_results_returns_empty(self):
        self.html('<main>No results for this search</main>')
        self.assertEqual(watcher.scan(self.page,'nothing',self.cfg),[])
    def test_unknown_page_reports_error(self):
        self.html('<main>Something went wrong</main>')
        with self.assertRaises(watcher.ScanError):watcher.scan(self.page,'test',self.cfg)
    def test_login_redirect_reports_session_problem(self):
        self.html('<main><script>if(location.pathname!="/i/flow/login")location.href="/i/flow/login";</script></main>')
        with self.assertRaises(watcher.ScanError) as error:watcher.scan(self.page,'test',self.cfg)
        self.assertEqual(error.exception.code,'login_required')


if __name__=='__main__':unittest.main()
