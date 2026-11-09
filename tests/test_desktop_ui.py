import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Native UI requires a display (use xvfb-run)')
class DesktopConsoleTests(unittest.TestCase):
    def setUp(self):
        from desktop_ui import build_console
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.platform = SimpleNamespace(root=root, runtime=root, prepare=Mock(), login=Mock(),
                                        open=Mock(), ai=Mock(), save=Mock(), contacts=Mock())
        self.app = build_console(self.platform, preview=True)
        self.addCleanup(self.app.destroy)
        self.app.update()

    def test_preview_does_not_start_services_or_send_messages(self):
        self.platform.prepare.assert_not_called()
        self.platform.ai.assert_not_called()
        self.assertEqual(len(self.app.console['notebook'].tabs()), 3)
        self.assertEqual(self.app.console['fields']['apiKey'].get(), '')

    def test_tabs_and_scrolling_fit_minimum_window(self):
        self.app.geometry('960x680')
        for index in range(3):
            self.app.console['navigate'](index)
            self.app.update()
            self.assertEqual(self.app.console['notebook'].index('current'), index)
            canvas = self.app.console['canvases'][index]
            self.assertGreater(canvas.winfo_height(), 200)
            self.assertLessEqual(canvas.winfo_rootx()+canvas.winfo_width(), self.app.winfo_rootx()+self.app.winfo_width())
        self.app.console['canvases'][1].yview_moveto(1)
        self.assertGreater(self.app.console['canvases'][1].yview()[0], 0)

    def test_start_without_consent_remains_blocked(self):
        self.app.console['start']()
        self.platform.ai.assert_not_called()
        self.assertIn('授权', self.app.console['status'].get())

    def test_connected_backend_and_paused_ai_are_displayed_separately(self):
        self.app.console['apply_health']({'enabled':False,'paused':True,'ownerCommands':True,
            'connection':{'serviceReady':True,'authenticated':True,'online':True,'detail':'在线'}})
        first,second,_=self.app.console['connection_buttons']
        self.assertEqual(first.cget('text'),'后台已就绪');self.assertIn('disabled',first.state())
        self.assertEqual(second.cget('text'),'微信已登录');self.assertIn('disabled',second.state())
        self.assertIn('微信已连接',self.app.console['badge'].cget('text'))
        self.assertIn('已暂停',self.app.console['summary'].get())

    def test_backend_loss_does_not_leave_a_ready_badge_or_login_button(self):
        self.app.console['apply_health']({'enabled':True,'health':{'state':'ready'},
            'connection':{'serviceReady':False,'authenticated':False,'online':False,'detail':'无法连接'}})
        first,second,_=self.app.console['connection_buttons']
        self.assertNotIn('disabled',first.state());self.assertIn('disabled',second.state())
        self.assertIn('后台未连接',self.app.console['badge'].cget('text'))
        self.assertIn('暂不能自动回复',self.app.console['summary'].get())
