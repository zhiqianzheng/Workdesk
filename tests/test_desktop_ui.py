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
