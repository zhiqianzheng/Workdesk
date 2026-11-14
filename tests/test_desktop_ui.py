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

    def test_contact_wheel_scrolls_list_without_moving_page(self):
        self.app.console['navigate'](1)
        self.app.update()
        selection = self.app.console['selection']
        for i in range(80):
            selection.insert('end', 'Contact %s' % i)
        canvas = self.app.console['canvases'][1]
        canvas.yview_moveto(.3)
        self.app.update()
        before = canvas.yview()
        selection.event_generate('<Button-5>')
        self.app.update()
        self.assertGreater(selection.yview()[0], 0)
        self.assertEqual(canvas.yview(), before)
        selection.yview_moveto(1)
        selection.event_generate('<Button-5>')
        self.app.update()
        self.assertEqual(canvas.yview(), before)

    def test_wheel_does_not_change_model(self):
        model = self.app.console['fields']['model']
        model.configure(values=['first', 'second'])
        model.set('first')
        model.event_generate('<Button-5>')
        self.app.update()
        self.assertEqual(model.get(), 'first')

    def test_scope_marks_follow_saved_selection_and_rollback(self):
        self.platform.update_scope = Mock(return_value={'status':'saved'})
        ui = self.app.console
        ui['show_contacts']([{'id':'a','nickname':'Alice'}, {'id':'b','nickname':'Bob'}])
        ui['selection'].selection_set(0)
        ui['selection'].event_generate('<<ListboxSelect>>')
        self.app.update()
        self.assertTrue(ui['selection'].get(0).startswith('☑'))
        self.assertTrue(ui['selection'].get(1).startswith('☐'))
        self.assertIn('已生效', ui['scope_note'].get())
        self.platform.update_scope.side_effect = ValueError('save failed')
        ui['selection'].selection_set(1)
        ui['selection'].event_generate('<<ListboxSelect>>')
        self.app.update()
        self.assertTrue(ui['selection'].get(1).startswith('☐'))
        self.assertIn('保存失败', ui['scope_note'].get())

    def test_take_over_and_cancel_all_apply_immediately(self):
        self.platform.update_scope = Mock(return_value={'status':'saved'})
        ui = self.app.console
        ui['show_contacts']([{'id':'a'}, {'id':'b'}])
        ui['set_entire_scope'](True)
        self.app.update()
        self.assertTrue(ui['allContacts'].get())
        self.assertTrue(ui['selection'].get(0).startswith('☑'))
        ui['set_entire_scope'](False)
        self.app.update()
        self.platform.update_scope.assert_called_with(False, [])
        self.assertFalse(ui['allContacts'].get())
        self.assertTrue(ui['selection'].get(0).startswith('☐'))

    def test_saved_consent_survives_reopen_but_new_endpoint_requires_confirmation(self):
        import json
        from desktop_ui import build_console
        from ai_reply import endpoint
        private = self.platform.root / 'private-data'
        private.mkdir(exist_ok=True)
        url = endpoint('https://example.com/v1')
        (private / 'workdesk-native-ai.json').write_text(json.dumps({'endpoint':url, 'consentEndpoint':url}))
        app = build_console(self.platform, preview=True)
        try:
            app.update()
            self.assertTrue(app.console['consent'].get())
            entry = app.console['fields']['endpoint']
            entry.delete(0, 'end')
            entry.insert(0, 'https://different.example/v1')
            self.assertFalse(app.console['consent'].get())
        finally:
            app.destroy()
