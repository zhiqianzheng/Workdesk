import json
import threading
import unittest
from concurrent.futures import Future
from http.server import ThreadingHTTPServer
from unittest.mock import Mock
import urllib.error
import urllib.request

from native_backend import NativeConnection
from server import Handler, Service


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = NativeConnection({'directory': '/unused', 'account': 'test'})
        self.addCleanup(self.connection.close)

    def test_first_snapshot_does_not_wait_for_every_directory_page(self):
        def backend(path, *args):
            if path == '':
                return {'authenticated': True, 'connection': 'online'}
            if path == 'threads?limit=100':
                return {'items': [{'id': 'first', 'kind': 'direct'}], 'nextCursor': 'page/2'}
            if path == 'threads/first':
                return {'id': 'first', 'kind': 'direct'}
            if path == 'threads/first/messages?limit=50':
                return {'items': []}
            self.fail('Unexpected eager page fetch: ' + path)
        self.connection.request = Mock(side_effect=backend)
        result = self.connection.snapshot()
        self.assertTrue(result['connected'])
        self.assertTrue(result['authenticated'])
        self.assertTrue(result['directoryLoading'])
        self.assertEqual(len(result['sessions']), 1)
        self.assertEqual(self.connection.request.call_count, 3)
        self.assertNotIn('threads/first', [call.args[0] for call in self.connection.request.call_args_list])

    def test_later_page_keeps_previously_loaded_contacts(self):
        self.connection.request = Mock(side_effect=[
            {'items': [{'id': 'a'}], 'nextCursor': 'page/2'},
            {'items': [{'id': 'b'}], 'nextCursor': None},
        ])
        self.connection.refresh_directory()
        self.assertEqual(list(self.connection.directory), ['a'])
        self.connection.directory_refresh_at = 0
        self.connection.refresh_directory()
        self.assertEqual(list(self.connection.directory), ['a', 'b'])
        self.assertFalse(self.connection.directory_scanning)
        self.assertIn('page%2F2', self.connection.request.call_args.args[0])

    def test_pagination_failure_retries_same_cursor_without_losing_cache(self):
        self.connection.request = Mock(side_effect=[
            {'items': [{'id': 'a'}], 'nextCursor': 'next'},
            TimeoutError(),
            {'items': [{'id': 'b'}]},
        ])
        self.connection.refresh_directory()
        self.connection.directory_refresh_at = 0
        with self.assertRaises(TimeoutError):
            self.connection.refresh_directory()
        self.assertEqual(list(self.connection.directory), ['a'])
        self.connection.directory_refresh_at = 0
        self.connection.refresh_directory()
        self.assertEqual(list(self.connection.directory), ['a', 'b'])
        self.assertEqual(self.connection.request.call_args_list[1], self.connection.request.call_args_list[2])

    def test_logged_in_timeout_is_not_reported_as_logged_out(self):
        self.connection.request = Mock(side_effect=[
            {'authenticated': True, 'connection': 'online'}, TimeoutError(),
        ])
        result = self.connection.snapshot()
        self.assertTrue(result['authenticated'])
        self.assertFalse(result['connected'])
        self.assertIn('已登录', result['detail'])
        self.assertIn('超时', result['detail'])
        self.assertFalse(result['canSend'])

    def test_logged_out_account_does_not_load_contacts(self):
        self.connection.request = Mock(return_value={'authenticated': False, 'connection': 'disconnected'})
        result = self.connection.snapshot()
        self.assertFalse(result['authenticated'])
        self.assertIn('扫码', result['detail'])
        self.connection.request.assert_called_once_with('')

    def test_invalid_local_token_is_not_misreported_as_wechat_logout(self):
        self.connection.request = Mock(side_effect=urllib.error.HTTPError('http://localhost', 401, '', {}, None))
        result = self.connection.snapshot()
        self.assertIn('访问凭据', result['detail'])


class SlowReadTests(unittest.TestCase):
    def setUp(self):
        self.service = Service()
        self.addCleanup(self.service.worker.shutdown, wait=True)

    def test_completed_read_is_not_discarded_by_next_poll(self):
        completed = Future()
        completed.set_result({'connected': True, 'sessions': []})
        self.service.read_future = completed
        self.assertIs(self.service.read(), completed)
        self.service.consume_read(completed)
        self.assertIsNone(self.service.read_future)

    def test_old_read_completion_does_not_clear_new_action_read(self):
        old, new = Future(), Future()
        self.service.read_future = new
        self.service.consume_read(old)
        self.assertIs(self.service.read_future, new)

    def test_http_poll_reports_pending_then_delivers_slow_result(self):
        completed = Future()
        self.service.read_future = completed
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        server.service = self.service
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def poll():
            req = urllib.request.Request('http://127.0.0.1:%s/api/state' % server.server_port,
                                         headers={'Authorization': 'Bearer ' + self.service.token})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
                return response.status, json.load(response)
        status, result = poll()
        self.assertEqual(status, 202)
        self.assertTrue(result['pending'])
        self.assertIs(self.service.read_future, completed)
        completed.set_result({'connected': True, 'sessions': [{'id': 'synthetic'}]})
        status, result = poll()
        self.assertEqual(status, 200)
        self.assertTrue(result['connected'])
        self.assertIsNone(self.service.read_future)


if __name__ == '__main__':
    unittest.main()
