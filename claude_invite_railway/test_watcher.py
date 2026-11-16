import unittest
from watcher import invite, classify, database, save
class Tests(unittest.TestCase):
    def test_invite(self):
        self.assertEqual(invite('https://claude.ai/duet-invite/ABC?code=123'),'https://claude.ai/duet-invite/ABC?code=123')
        self.assertIsNotNone(invite('https://claude.ai/duet-invite/'))
    def test_fake(self):
        for u in ['https://claude.ai.evil.com/duet-invite/a','https://claude.ai@evil.com/invite/a','http://claude.ai/invite/a','https://claude.ai/duet-invite-fake/a']:
            self.assertIsNone(invite(u))
    def test_request(self):
        self.assertIsNone(classify('Anyone have Claude 7 days trial invite?',[])[0])
        self.assertIsNotNone(classify('Sharing Claude 7-day free trial invite',[])[0])
    def test_direct_priority(self):
        self.assertTrue(classify('Hello',['https://claude.ai/duet-invite/abc'])[1])
    def test_dedupe(self):
        db=database(':memory:'); p={'invites':['https://claude.ai/duet-invite/a'],'post_url':'https://x.com/a/status/1'}
        save(db,p); p['post_url']='https://x.com/b/status/2'; save(db,p)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM hits').fetchone()[0],1)
if __name__=='__main__': unittest.main()
