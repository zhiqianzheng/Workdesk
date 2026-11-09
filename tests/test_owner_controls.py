from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from native_controls import OwnerControls, control_text
from native_watchdog import Supervisor


class OwnerControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / 'private-data'
        self.private.mkdir()
        (self.private / 'workdesk-native-ai.json').write_text(json.dumps({'account': 'owner'}))
        self.controls = OwnerControls(self.root)
        self.controls.request = Mock(return_value={'asOfEventCursor': '10'})
        self.controls.poll()

    def event(self, text, direction='outgoing', origin='live', cursor='11', **overrides):
        row = dict(id='m', body=text, type=1, direction=direction, accountId='owner',
                   threadId='anywhere', createdAt=datetime.now(timezone.utc).isoformat())
        row.update(overrides)
        event = dict(cursor=cursor, kind='message.committed', data=dict(
            direction=direction, origin=origin, messageId='m', threadId='anywhere'))
        self.controls.request.side_effect = lambda path: {'items': [event]} if path.startswith('events?') else row
        self.controls.poll()

    def test_first_boot_uses_current_boundary_not_old_messages(self):
        self.assertEqual(json.loads(self.controls.path.read_text())['cursor'], '10')
        self.controls.request.assert_called_once_with('threads?limit=1')

    def test_intent_aliases_but_not_substrings_or_negations(self):
        self.assertEqual(control_text(' 停止AI回复\n'), 'pause')
        for text in ['关闭AI回复', '暂停 ai 回复。', '帮我先把AI自动回复关掉吧', '请关闭AI回复功能', '先关一下AI回复']:
            self.assertEqual(control_text(text), 'pause', text)
        for text in ['打开AI回复', '开启ＡＩ回复', '请恢复AI自动回复吧', '把AI回复打开', '现在启动AI回复']:
            self.assertEqual(control_text(text), 'start', text)
        for text in ['他说停止AI回复', '“停止AI回复”', '不要关闭AI回复', '别打开AI回复',
                     '如果有人说开启AI回复', '开启AI回复？', '停止回复', None]:
            self.assertIsNone(control_text(text))

    def test_owner_can_stop_from_any_conversation_including_local_ui(self):
        for origin in ['live', 'catchup', 'local_send']:
            self.event('停止AI回复', origin=origin)
            self.assertTrue(self.controls.stop.exists())
            self.controls.stop.unlink()

    def test_friend_cannot_stop_or_start(self):
        self.event('停止AI回复', direction='incoming')
        self.assertFalse(self.controls.stop.exists())
        self.event('开启AI回复', direction='incoming')
        self.assertIsNone(json.loads(self.controls.path.read_text())['pendingStart'])

    def test_canonical_direction_account_and_type_are_verified(self):
        for overrides in [dict(accountId='other'), dict(type=49), dict(threadId='other'),
                          dict(createdAt='2020-01-01T00:00:00Z')]:
            self.event('停止AI回复', **overrides)
            self.assertFalse(self.controls.stop.exists())
        self.controls.request.side_effect = None
        # A misleading outgoing event cannot override the canonical incoming row.
        event={'cursor':'12','kind':'message.committed','data':{'direction':'outgoing','origin':'live','messageId':'m','threadId':'anywhere'}}
        self.controls.request.side_effect = [{'items':[event]}, {'body':'停止AI回复','direction':'incoming','type':1}]
        self.controls.poll()
        self.assertFalse(self.controls.stop.exists())

    def test_resume_waits_for_old_worker_and_discards_paused_backlog(self):
        self.controls.stop.touch()
        state = dict(account='owner', cursor='5', queue={'friend':['old']}, inFlight={'uncertain':['m']},
                     blocked={'existing':'unknown'}, replies=2)
        path=self.private/'native-ai-state.json';path.write_text(json.dumps(state))
        self.event('开启AI回复', cursor='15')
        self.assertFalse(self.controls.resume_if_ready(True))
        self.assertTrue(self.controls.stop.exists())
        self.assertTrue(self.controls.resume_if_ready(False))
        self.assertFalse(self.controls.stop.exists())
        saved=json.loads(path.read_text())
        self.assertEqual(saved['cursor'],'15')
        self.assertEqual(saved['queue'],{})
        self.assertEqual(saved['inFlight'],{})
        self.assertEqual(set(saved['blocked']),{'existing','uncertain'})
        self.assertEqual(saved['replies'],2)

    def test_later_manual_pause_overrides_pending_start(self):
        self.controls.stop.touch()
        self.event('开启AI回复')
        stamp=self.controls.stop.stat().st_mtime_ns
        import os
        os.utime(self.controls.stop, ns=(stamp+10000000,stamp+10000000))
        self.assertFalse(self.controls.resume_if_ready(False))
        self.assertTrue(self.controls.stop.exists())

    def test_supervisor_keeps_polling_commands_while_paused(self):
        self.controls.stop.touch()
        (self.private/'watchdog.enabled').touch()
        guard=Supervisor(self.root)
        guard.controls=Mock()
        with patch('native_watchdog.NativeAI.process_alive',return_value=False), patch('native_watchdog.subprocess.Popen') as spawn:
            self.assertEqual(guard.tick(),'paused')
        guard.controls.poll.assert_called_once()
        spawn.assert_not_called()

    def test_supervisor_restarts_after_start_command_even_while_paused(self):
        self.controls.stop.touch()
        (self.private/'watchdog.enabled').touch()
        self.event('开启AI回复')
        guard=Supervisor(self.root);guard.controls=self.controls
        guard.controls.poll=Mock()
        with patch('native_watchdog.NativeAI.process_alive',return_value=False), patch('native_watchdog.subprocess.Popen') as spawn:
            self.assertEqual(guard.tick(),'restarting')
        self.assertFalse(self.controls.stop.exists())
        spawn.assert_called_once()
