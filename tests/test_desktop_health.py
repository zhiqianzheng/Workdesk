import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from desktop_app import Platform


class DesktopHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);p=self.root/'private-data';p.mkdir()
        (p/'api-token').write_text('synthetic')
        (p/'workdesk-native-ai.json').write_text(json.dumps({'account':'owner'}))
        self.app=Platform(root=self.root,runtime=self.root,vendor=self.root/'wx')

    def probe(self,items):
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'items':items}).encode()
        with patch('desktop_app.urllib.request.build_opener') as opener, patch('desktop_app.NativeConnection'):
            opener.return_value.open.return_value=response
            return self.app.connection_status()

    def test_existing_account_is_restored_without_prepare_or_login(self):
        self.assertEqual(self.app.account,'owner')
        self.assertTrue(self.probe([{'id':'owner','authenticated':True,'connection':'online'}])['online'])

    def test_logged_in_connecting_and_logged_out_are_distinct(self):
        value=self.probe([{'id':'owner','authenticated':True,'connection':'connecting'}])
        self.assertTrue(value['authenticated']);self.assertFalse(value['online'])
        value=self.probe([{'id':'owner','authenticated':False,'connection':'offline'}])
        self.assertTrue(value['serviceReady']);self.assertFalse(value['authenticated'])

    def test_ready_backend_is_reused_even_if_daemon_start_would_reject_ownership(self):
        self.app.wx.write_bytes(b'synthetic')
        with patch('desktop_app.WX_HASH',hashlib.sha256(b'synthetic').hexdigest()), \
             patch.object(self.app,'connection_status',return_value={'serviceReady':True,'online':True}), \
             patch.object(self.app,'cli',side_effect=ValueError('ownership mismatch')) as cli:
            self.assertTrue(self.app.prepare())
        cli.assert_not_called()

    def test_unexpected_account_is_not_silently_adopted(self):
        value=self.probe([{'id':'other','authenticated':True,'connection':'online'}])
        self.assertEqual(value['errorKind'],'accounts');self.assertFalse(value['online'])
        self.assertEqual(self.app.account,'owner')

    def test_health_reports_wechat_online_while_ai_is_paused(self):
        with patch.object(self.app,'connection_status',return_value={'online':True}),patch('desktop_app.NativeAI') as ai:
            ai.return_value.public.return_value={'enabled':False,'paused':True}
            value=self.app.health()
        self.assertTrue(value['connection']['online']);self.assertTrue(value['paused'])
