import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from config_store import edit_config


class ConfigStoreTests(unittest.TestCase):
    def test_concurrent_edits_do_not_drop_fields_and_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            path.write_text(json.dumps({'unchanged':'keep'}))
            def update(i):
                with edit_config(path) as value:value[str(i)]=i
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:list(pool.map(update,range(10)))
            value=json.loads(path.read_text())
            self.assertEqual(len(value),11)
            self.assertEqual(value['unchanged'],'keep')
            with self.assertRaises(ValueError):
                with edit_config(path) as draft:
                    draft.clear()
                    raise ValueError('cancel')
            self.assertEqual(json.loads(path.read_text()),value)
