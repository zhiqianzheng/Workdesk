import unittest
from unittest.mock import patch
from native_backend import NativeAI


@unittest.skipUnless(__import__('sys').platform.startswith('linux'), 'Linux procfs regression')
class ProcessAliveTests(unittest.TestCase):
    @patch('native_backend.os.kill')
    @patch('native_backend.Path.read_text', return_value='123 (worker (name)) Z 1 0 0')
    def test_exited_zombie_does_not_block_restart(self, read, kill):
        self.assertFalse(NativeAI.process_alive(123))

    @patch('native_backend.os.kill')
    @patch('native_backend.Path.read_text', return_value='123 (worker) S 1 0 0')
    def test_sleeping_live_worker_is_still_running(self, read, kill):
        self.assertTrue(NativeAI.process_alive(123))

    @patch('native_backend.os.kill')
    @patch('native_backend.Path.read_text', side_effect=PermissionError())
    def test_procfs_restriction_is_not_treated_as_exit(self, read, kill):
        self.assertTrue(NativeAI.process_alive(123))

    @patch('native_backend.os.kill', side_effect=ProcessLookupError())
    def test_missing_worker_is_stopped(self, kill):
        self.assertFalse(NativeAI.process_alive(123))


if __name__ == '__main__':
    unittest.main()
