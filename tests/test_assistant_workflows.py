import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import assistant_profiles as profiles
import reply_review as review
import settings_backup as backup


class AssistantWorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.private=self.root/'private-data';self.private.mkdir()
        self.config=self.private/'workdesk-native-ai.json'
        self.config.write_text(json.dumps({'style':'original','allContacts':True,'encryptedKey':'private','account':'owner','ownerEpoch':'keep'}))

    def test_contact_style_memory_isolation_and_review_disables_tools(self):
        profiles.save_profile(self.root,'a','随口','只聊技术','review')
        a=profiles.load_profile(self.root,'a')
        config=profiles.apply_profile({'webSearch':True,'mediaReplies':True,'style':'default'},a)
        self.assertIn('只聊技术',config['style']);self.assertFalse(config['mediaReplies'])
        self.assertEqual(profiles.load_profile(self.root,'b'),{})
        profiles.save_profile(self.root,'a','','','auto')
        self.assertEqual(profiles.load_profile(self.root,'a')['memory'],'')

    def test_review_dedupe_approval_claim_and_unknown_are_durable(self):
        review.enqueue(self.root,'owner','a','key','draft')
        review.enqueue(self.root,'owner','a','key','duplicate')
        self.assertEqual(review.pending(self.root)[0]['text'],'draft')
        self.assertIsNone(review.claim(self.root,'owner'))
        review.decide(self.root,'key',True)
        self.assertIsNone(review.claim(self.root,'different-account'))
        self.assertEqual(review.claim(self.root,'owner')['text'],'draft')
        self.assertIsNone(review.claim(self.root,'owner'))
        review.finish(self.root,'key','unknown')
        self.assertEqual(review.pending(self.root)[0]['state'],'unknown')
        with self.assertRaises(ValueError):review.decide(self.root,'key',True)

    def test_expired_draft_cannot_be_approved(self):
        review.enqueue(self.root,'owner','a','key','draft')
        with patch('reply_review.time.time',return_value=10**12):
            with self.assertRaises(ValueError):review.decide(self.root,'key',True)
            self.assertEqual(review.pending(self.root),[])

    def test_backup_restores_only_preferences_and_retains_undo(self):
        profiles.save_profile(self.root,'a','casual','note','auto')
        snapshot=backup.create(self.root)
        self.assertNotIn('encryptedKey',Path(snapshot).read_text())
        config=json.loads(self.config.read_text());config.update(style='changed',encryptedKey='new-private')
        self.config.write_text(json.dumps(config))
        backup.restore(self.root,snapshot)
        config=json.loads(self.config.read_text())
        self.assertEqual(config['style'],'original');self.assertEqual(config['encryptedKey'],'new-private')
        self.assertEqual(config['ownerEpoch'],'keep')
        self.assertEqual(len(list((self.private/'settings-backups').glob('*.json'))),2)

    def test_corrupt_or_external_backup_cannot_change_configuration(self):
        snapshot=Path(backup.create(self.root));record=json.loads(snapshot.read_text());record['payload']='tampered'
        snapshot.write_text(json.dumps(record));before=self.config.read_text()
        with self.assertRaises(ValueError):backup.restore(self.root,str(snapshot))
        self.assertEqual(self.config.read_text(),before)
        with self.assertRaises(ValueError):backup.inspect(self.root,str(self.config))

    def test_review_pipeline_cannot_send_before_approval_and_rechecks_scope(self):
        import native_listener as listener
        from unittest.mock import Mock
        from contextlib import ExitStack
        config={'account':'owner','allContacts':True,'encryptedKey':'','style':'plain'}
        self.config.write_text(json.dumps(config))
        profiles.save_profile(self.root,'friend','','','review')
        rows=[{'id':'m','threadId':'friend','type':1,'body':'你好','direction':'incoming','createdAt':'2026-11-14T00:00:00Z'}]
        def request(path,data=None,key=None):
            if path=='threads/friend':return {'id':'friend','kind':'direct'}
            if path.endswith('/messages?limit=20'):return {'items':rows}
            if path=='sends':return {'state':'accepted','serverId':'synthetic'}
            raise AssertionError(path)
        calls=Mock(side_effect=request)
        with ExitStack() as stack:
            stack.enter_context(patch.multiple(listener,ROOT=self.root,PRIVATE=self.private,STOP=self.private/'stop',CONFIG=config,BASE='http://localhost/',create=True))
            stack.enter_context(patch.object(listener,'request',calls))
            stack.enter_context(patch.object(listener,'context_for',return_value=[]))
            stack.enter_context(patch.object(listener,'generate',return_value='嗨'))
            result=listener.work('friend',['m'])
            self.assertEqual(result['state'],'pending_review')
            self.assertFalse(any(c.args[0]=='sends' for c in calls.call_args_list))
            draft=review.pending(self.root)[0];review.decide(self.root,draft['key'],True)
            listener.dispatch_approved()
            listener.dispatch_approved()
            self.assertEqual(sum(c.args[0]=='sends' for c in calls.call_args_list),1)
            review.enqueue(self.root,'owner','friend','other','cancel this')
            review.decide(self.root,'other',True)
            self.config.write_text(json.dumps({'allContacts':False,'contacts':[]}))
            listener.dispatch_approved()
            self.assertEqual(sum(c.args[0]=='sends' for c in calls.call_args_list),1)
