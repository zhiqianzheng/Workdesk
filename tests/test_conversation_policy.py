import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import native_listener as listener


class ConversationPolicyTests(TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.private=Path(tmp.name)
        self.config={'account':'synthetic','allContacts':True}
        (self.private/'workdesk-native-ai.json').write_text(json.dumps(self.config))
        context=patch.multiple(listener,PRIVATE=self.private,CONFIG=self.config,create=True)
        context.start();self.addCleanup(context.stop)

    def test_group_requires_explicit_address_but_direct_chat_does_not(self):
        self.assertFalse(listener.group_addressed({'kind':'group'},[{'body':'随口闲聊'}]))
        self.assertTrue(listener.group_addressed({'kind':'group'},[{'mentions':{'self':True}}]))
        self.assertTrue(listener.group_addressed({'kind':'group'},[{'quote':{'direction':'outgoing'}}]))
        self.assertTrue(listener.group_addressed({'kind':'direct'},[]))
        self.config['groupMentionsOnly']=False
        self.assertTrue(listener.group_addressed({'kind':'group'},[]))

    def test_manual_live_message_holds_thread_and_expiry_resumes(self):
        row={'accountId':'synthetic','threadId':'friend','direction':'outgoing','type':1,
             'body':'我来处理','createdAt':datetime.now(timezone.utc).isoformat()}
        event={'kind':'message.committed','data':{'threadId':'friend','direction':'outgoing','origin':'live','messageId':'m'}}
        with patch.object(listener,'request',return_value=row):listener.observe_manual(event,time.time()-30)
        self.assertFalse(listener.can_reply('friend'))
        self.assertTrue(listener.can_reply('other'))
        with patch.object(listener.time,'time',return_value=time.time()+601):
            self.assertTrue(listener.can_reply('friend'))

    def test_own_api_sends_and_old_messages_do_not_trigger_takeover(self):
        event={'kind':'message.committed','data':{'direction':'outgoing','origin':'local_send','messageId':'m'}}
        with patch.object(listener,'request') as request:
            listener.observe_manual(event,0)
            request.assert_not_called()
        event['data'].update(origin='live',threadId='friend')
        row={'accountId':'synthetic','threadId':'friend','direction':'outgoing','createdAt':'2020-01-01T00:00:00Z'}
        with patch.object(listener,'request',return_value=row):listener.observe_manual(event,0)
        self.assertEqual(listener.manual_holds(),{})

    def test_scope_change_is_read_without_restart(self):
        self.assertTrue(listener.can_reply('friend'))
        (self.private/'workdesk-native-ai.json').write_text(json.dumps({'allContacts':False,'contacts':[]}))
        self.assertFalse(listener.can_reply('friend'))

    def test_preview_uses_synthetic_input_without_media_tools(self):
        from desktop_app import Platform
        config=self.private/'private-data'
        config.mkdir()
        (config/'workdesk-native-ai.json').write_text(json.dumps({'model':'test','encryptedKey':'','webSearch':True,'mediaReplies':True}))
        app=Platform(root=self.private)
        with patch('ai_reply.generate',return_value='收到') as generate:
            self.assertEqual(app.preview_reply('测试一下'),'收到')
        settings,records=generate.call_args.args
        self.assertFalse(settings['webSearch'])
        self.assertFalse(settings['mediaReplies'])
        self.assertEqual(records[0]['text'],'测试一下')
