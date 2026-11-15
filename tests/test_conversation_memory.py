import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import conversation_memory as memory


class ConversationMemoryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);(self.root/'private-data').mkdir()
        (self.root/'private-data/workdesk-native-ai.json').write_text('{}')
        self.row={'id':'m1','accountId':'a','threadId':'friend','senderId':'person','direction':'incoming','type':1,'body':'我用的是RK3566开发板，平时用Linux开发','createdAt':'2026-11-14T00:00:00+00:00'}

    def test_learns_once_and_vector_recall_is_account_thread_scoped(self):
        memory.learn(self.root,'a','friend',[self.row,self.row])
        self.assertEqual(len(memory.inspect(self.root,'a','friend')['items']),1)
        hits=memory.recall(self.root,'a','friend','RK3566开发板')
        self.assertEqual(hits[0]['sender'],'person')
        self.assertEqual(memory.recall(self.root,'other','friend','RK3566开发板'),[])
        self.assertEqual(memory.recall(self.root,'a','different','RK3566开发板'),[])
        self.assertEqual(memory.recall(self.root,'a','friend','RK3566开发板',exclude=['m1']),[])
        self.assertEqual(memory.recall(self.root,'a','friend','香蕉牛奶奶茶'),[])

    def test_disable_stops_learning_and_recall_and_delete_cannot_relearn(self):
        memory.learn(self.root,'a','friend',[self.row])
        memory.manage(self.root,'a','friend','delete','m1')
        memory.learn(self.root,'a','friend',[self.row])
        self.assertEqual(memory.inspect(self.root,'a','friend')['items'],[])
        memory.manage(self.root,'a','friend','disable')
        memory.learn(self.root,'a','friend',[dict(self.row,id='m2')])
        self.assertEqual(memory.inspect(self.root,'a','friend')['items'],[])
        self.assertEqual(memory.recall(self.root,'a','friend','RK3566开发板'),[])

    def test_never_learns_own_outputs_or_wrong_thread(self):
        memory.learn(self.root,'a','friend',[dict(self.row,direction='outgoing'),dict(self.row,threadId='other')])
        self.assertEqual(memory.inspect(self.root,'a','friend')['items'],[])

    def test_clear_sets_boundary_without_replaying_old_messages(self):
        memory.learn(self.root,'a','friend',[self.row]);memory.manage(self.root,'a','friend','clear')
        memory.learn(self.root,'a','friend',[self.row])
        self.assertEqual(memory.inspect(self.root,'a','friend')['items'],[])

    def test_optional_semantic_vectors_recall_synonyms_and_fallback(self):
        with patch.object(memory,'semantic_vectors',return_value=[{'model':'test','values':[1.,0.]}]):
            memory.learn(self.root,'a','friend',[self.row])
            self.assertEqual(len(memory.recall(self.root,'a','friend','单板电脑型号')),1)
        with patch.object(memory,'semantic_vectors',side_effect=ValueError('unavailable')):
            self.assertEqual(len(memory.recall(self.root,'a','friend','RK3566开发板')),1)
