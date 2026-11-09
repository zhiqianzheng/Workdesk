import unittest
from unittest.mock import Mock
from native_backend import NativeConnection, SUBSCRIPTIONS, key


class NativeBackTests(unittest.TestCase):
    def setUp(self):
        self.connection = NativeConnection({'directory': '/unused', 'account': 'test'})
        self.addCleanup(self.connection.close)
        self.connection.directory = {
            'gh_synthetic': {'id': 'gh_synthetic', 'kind': 'direct', 'classification': {'category': 'business'}},
            'friend': {'id': 'friend', 'kind': 'direct'},
        }
        self.connection.directory_refresh_at = float('inf')
        def backend(path, *args):
            if path == '':
                return {'authenticated': True, 'connection': 'online'}
            if path.endswith('/messages?limit=50'):
                return {'items': []}
            if path.startswith('threads/'):
                return self.connection.directory[path.split('/')[1]]
            self.fail('Unexpected native operation: ' + path)
        self.connection.request = Mock(side_effect=backend)

    def test_public_account_enables_back(self):
        self.connection.snapshot()
        state = self.connection.select('gh_synthetic')
        self.assertEqual(state['current']['key'], key('gh_synthetic'))
        self.assertTrue(state['canGoBack'])
        self.assertFalse(state['canSend'])

    def test_back_clears_selection_history_and_does_not_reselect_on_poll(self):
        self.connection.snapshot()
        self.connection.select('gh_synthetic')
        self.connection.history = True
        self.connection.rows = [{'id': 'old', 'text': 'synthetic'}]
        self.connection.cursor = 'older'
        state = self.connection.navigate_back()
        for state in (state, self.connection.snapshot()):
            self.assertTrue(state['connected'])
            self.assertIsNone(state['current'])
            self.assertEqual(len(state['sessions']), 2)
            self.assertEqual(state['records'], [])
            self.assertFalse(state['canGoBack'])
            self.assertFalse(state['canSend'])
            self.assertFalse(state['canSendImage'])
        self.assertFalse(self.connection.history)
        self.assertIsNone(self.connection.cursor)

    def test_selecting_friend_after_back_reopens_conversation(self):
        self.connection.snapshot()
        self.connection.navigate_back()
        state = self.connection.select('friend')
        self.assertEqual(state['current']['key'], key('friend'))
        self.assertTrue(state['canSend'])
        self.assertTrue(state['canGoBack'])

    def test_root_groups_public_accounts_without_mixing_them_with_friends(self):
        state = self.connection.snapshot()
        self.assertEqual(state['directoryView'], 'root')
        self.assertEqual([s['id'] for s in state['sessions']], [SUBSCRIPTIONS, 'friend'])
        self.assertEqual(state['current']['key'], key('friend'))
        self.assertEqual(state['sessions'][0]['folder'], 'subscriptions')

    def test_folder_has_back_even_without_a_selected_public_account(self):
        self.connection.snapshot()
        state = self.connection.select(SUBSCRIPTIONS)
        self.assertEqual(state['directoryView'], 'subscriptions')
        self.assertTrue(state['canGoBack'])
        self.assertIsNone(state['current'])
        self.assertEqual([s['id'] for s in state['sessions']], ['gh_synthetic'])
        self.assertTrue(self.connection.snapshot()['canGoBack'])
        state = self.connection.navigate_back()
        self.assertEqual(state['directoryView'], 'root')
        self.assertEqual([s['id'] for s in state['sessions']], [SUBSCRIPTIONS, 'friend'])
        self.assertFalse(state['canGoBack'])

    def test_search_selection_of_public_account_enters_its_parent_folder(self):
        self.connection.snapshot()
        state = self.connection.select('gh_synthetic')
        self.assertEqual(state['directoryView'], 'subscriptions')
        self.assertTrue(state['canGoBack'])
        self.assertEqual([s['id'] for s in state['sessions']], ['gh_synthetic'])
        self.assertEqual(self.connection.navigate_back()['directoryView'], 'root')

    def test_unknown_classification_does_not_leave_public_id_at_root_or_enable_sending(self):
        info = {'id': 'gh_unknown', 'kind': 'direct', 'classification': {'category': 'unknown'}}
        self.assertTrue(self.connection.public_account(info))
        self.assertFalse(self.connection.writable(info))

    def test_back_invalidates_previous_send_binding(self):
        self.connection.snapshot()
        self.connection.select('gh_synthetic')
        old_binding = key('gh_synthetic')
        self.connection.navigate_back()
        before = self.connection.request.call_count
        result = self.connection.send(old_binding, 'synthetic draft')
        self.assertEqual(result['state'], 'not_sent')
        self.assertEqual(self.connection.request.call_count, before)


if __name__ == '__main__':
    unittest.main()
