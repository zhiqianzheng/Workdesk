import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from server import Handler


class SessionReconnectTests(unittest.TestCase):
    def test_old_token_recovery_is_same_origin_only(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.service = SimpleNamespace(token='replacement-token')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            request = urllib.request.Request(base + '/api/health', headers={'Authorization': 'Bearer expired'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(request)
            self.assertEqual(error.exception.code, 401)
            for headers in ({}, {'Origin': 'https://evil.example', 'X-Workdesk-Reconnect': '1'},
                            {'Origin': base}, {'Origin': base, 'X-Workdesk-Reconnect': '1', 'Sec-Fetch-Site': 'cross-site'}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(urllib.request.Request(base + '/api/session/reconnect', data=b'', headers=headers))
                self.assertEqual(error.exception.code, 403)
            headers = {'Origin': base, 'X-Workdesk-Reconnect': '1', 'Sec-Fetch-Site': 'same-origin'}
            with opener.open(urllib.request.Request(base + '/api/session/reconnect', data=b'', headers=headers)) as response:
                token = json.load(response)['token']
            with opener.open(urllib.request.Request(base + '/api/health', headers={'Authorization': 'Bearer ' + token})) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
