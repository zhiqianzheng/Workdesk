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

    def test_manual_message_and_old_hold_never_pause_contact(self):
        (self.private/'manual-takeover.json').write_text(json.dumps({'friend':time.time()+600}))
        with patch.object(listener,'request') as request:
            listener.observe_manual({'kind':'message.committed','data':{'direction':'outgoing','origin':'live','threadId':'friend','messageId':'m'}},0)
            request.assert_not_called()
        self.assertTrue(listener.can_reply('friend'))
        self.assertEqual(listener.manual_holds(),{})

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

    def test_retired_memory_and_preview_actions_are_not_exposed(self):
        from desktop_app import Platform
        for name in ('conversation_memory','history_memory_import','history_memory_preview','review_drafts','backup_settings','preview_reply'):
            self.assertFalse(hasattr(Platform,name))
