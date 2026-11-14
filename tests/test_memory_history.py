from datetime import datetime,timezone
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import memory_history as history
import conversation_memory as memory


class MemoryHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);private=self.root/'private-data';private.mkdir()
        self.config={'account':'owner','model':'test','endpoint':'http://localhost/v1/chat/completions','encryptedKey':''}
        (private/'workdesk-native-ai.json').write_text(json.dumps(self.config))
        self.row={'id':'m','accountId':'owner','threadId':'friend','senderId':'person','type':1,'direction':'incoming','body':'我在用RK3566开发板学习Linux驱动','createdAt':datetime.now(timezone.utc).isoformat()}

    def test_preview_reads_only_requested_thread_and_skips_own_outputs(self):
        connection=Mock();connection.writable.return_value=True
        connection.request.side_effect=[{'id':'friend','displayName':'Friend'}, {'items':[self.row,dict(self.row,id='own',direction='outgoing'),dict(self.row,id='wrong',threadId='other')]}]
        result=history.preview(connection,'owner','friend',30)
        self.assertEqual([r['id'] for r in result['rows']],['m'])
        self.assertTrue(all(c.args[0].startswith('threads/friend') for c in connection.request.call_args_list))

    def data(self):
        return {'account':'owner','thread':'friend','createdAt':time.time(),'rows':[self.row],'limited':False}

    def test_ai_import_keeps_sources_and_dedupes_without_sending(self):
        response={'choices':[{'message':{'content':json.dumps({'memories':[{'source':'m','text':'使用RK3566开发板'},{'source':'invented','text':'不能收录'}]})}}]}
        with patch('api_diagnostics.request',return_value=response) as request:
            result=history.import_preview(self.root,self.config,self.data())
            history.import_preview(self.root,self.config,self.data())
        self.assertEqual(result['summaries'],1)
        rows=memory.inspect(self.root,'owner','friend')['items']
        self.assertEqual(len(rows),2)
        self.assertTrue(any('原话：' in r['text'] for r in rows))
        self.assertTrue(all(c.args[1].endswith('/chat/completions') for c in request.call_args_list))

    def test_expired_or_wrong_account_preview_is_rejected_before_api(self):
        data=self.data();data['createdAt']=0
        with patch('api_diagnostics.request') as request:
            with self.assertRaises(ValueError):history.import_preview(self.root,self.config,data)
            data=self.data();data['account']='other'
            with self.assertRaises(ValueError):history.import_preview(self.root,self.config,data)
            request.assert_not_called()

    def test_deleted_source_is_not_resurrected_by_import(self):
        memory.learn(self.root,'owner','friend',[self.row]);memory.manage(self.root,'owner','friend','delete','m')
        with patch('api_diagnostics.request') as request:
            with self.assertRaises(ValueError):history.import_preview(self.root,self.config,self.data())
            request.assert_not_called()
        self.assertEqual(memory.inspect(self.root,'owner','friend')['items'],[])

    def test_invalid_model_output_does_not_partially_import(self):
        with patch('api_diagnostics.request',return_value={'choices':[{'message':{'content':'not json'}}]}):
            with self.assertRaises(ValueError):history.import_preview(self.root,self.config,self.data())
        self.assertEqual(memory.inspect(self.root,'owner','friend')['items'],[])
