from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from native_controls import OwnerControls, control_text
from native_watchdog import Supervisor
from native_ai_context import replyable, context_for


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

    def test_account_transport_uses_account_resource_without_trailing_slash(self):
        from unittest.mock import MagicMock
        (self.private/'api-token').write_text('synthetic')
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"authenticated":true}'
        with patch('native_controls.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            self.assertTrue(OwnerControls(self.root).request('')['authenticated'])
        self.assertEqual(opener.return_value.open.call_args.args[0].full_url,'http://127.0.0.1:6175/v1/accounts/owner')

    def test_query_aliases_and_unauthorized_query_is_ignored(self):
        for text in ['查询AI回复状态', '查询AI自动回复状态', '请查看 ai 自动回复的状态。']:
            self.assertEqual(control_text(text), 'status')
            self.assertFalse(replyable(dict(type=1,direction='incoming',body=text)))
        self.event('查询AI回复状态', direction='incoming')
        self.assertFalse(json.loads(self.controls.path.read_text()).get('queries'))
        self.assertFalse(self.controls.stop.exists())

    def test_owner_status_feedback_works_while_paused_and_is_idempotent(self):
        self.controls.stop.touch()
        row=dict(id='query1',body='查询AI回复状态',type=1,direction='outgoing',accountId='owner',
                 threadId='filehelper',createdAt=datetime.now(timezone.utc).isoformat())
        event=dict(cursor='12',kind='message.committed',data=dict(direction='outgoing',origin='live',messageId='query1',threadId='filehelper'))
        calls=[]
        def request(path,data=None,key=None):
            if path.startswith('events?'):return {'items':[event]}
            if path=='messages/query1':return row
            if path=='':return {'authenticated':True,'connection':'online'}
            if path=='sends':
                calls.append((data,key));return {'state':'accepted','serverId':'confirmed'}
            self.fail(path)
        self.controls.request=Mock(side_effect=request)
        self.controls.poll();self.controls.poll()
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0]['threadId'],'filehelper')
        self.assertIn('已暂停',calls[0][0]['text'])
        self.assertTrue(calls[0][1].startswith('owner-status-'))
        self.assertTrue(self.controls.stop.exists())

    def test_uncertain_status_send_retries_same_key_and_payload(self):
        state=json.loads(self.controls.path.read_text());state['queries']={'q':{'thread':'filehelper'}}
        self.controls.status_text=Mock(return_value='AI 状态：暂停')
        self.controls.request=Mock(side_effect=[TimeoutError(),{'state':'accepted','serverId':'confirmed'}])
        with self.assertRaises(TimeoutError):self.controls.flush_queries(state)
        first=self.controls.request.call_args
        self.controls.flush_queries(state)
        self.assertEqual(self.controls.request.call_args,first)
        self.controls.status_text.assert_called_once()

    def test_status_checks_process_heartbeat_and_blocked_sessions(self):
        import time
        path=self.private/'global-status.json'
        self.controls.request=Mock(return_value={'authenticated':True,'connection':'online'})
        status=dict(pid=1,state='listening',updatedAt=time.time(),blocked=0,active=0,queued=0)
        path.write_text(json.dumps(status))
        with patch('native_backend.NativeAI.process_alive',return_value=True):
            self.assertIn('已开启，正在监听',self.controls.status_text())
            status['blocked']=1;path.write_text(json.dumps(status))
            self.assertIn('需要检查',self.controls.status_text())
            status.update(blocked=0,updatedAt=0);path.write_text(json.dumps(status))
            self.assertIn('未就绪',self.controls.status_text())
        with patch('native_backend.NativeAI.process_alive',return_value=False):
            self.assertIn('未就绪',self.controls.status_text())

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

    def test_friend_control_messages_are_not_answered_or_given_to_model(self):
        row=dict(id='m',direction='incoming',type=1,body='请关闭AI回复',createdAt='2026-01-01T00:00:00Z')
        self.assertFalse(replyable(row))
        question={**row,'id':'q','body':'今天吃什么'}
        self.assertTrue(replyable(question))
        with patch('native_ai_context.Previews'):
            result=context_for([row,question],[question],None,None,None)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['text'],'今天吃什么')

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
