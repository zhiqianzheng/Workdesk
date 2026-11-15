from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import chat_report


class ChatReportTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.config={'account':'owner','model':'test','endpoint':'http://localhost/v1/chat/completions','encryptedKey':''}
        self.rows=[self.row(i) for i in range(620)]
    def row(self,i,body=None):
        return {'id':'m%s'%i,'accountId':'owner','threadId':'group','senderId':'person','direction':'incoming' if i%2 else 'outgoing','type':1,'body':body or '讨论Linux驱动进展%s'%i,'createdAt':'2026-01-15T12:00:00+00:00'}
    def connection(self,rows):
        def request(path):
            if path=='threads/group':return {'id':'group','kind':'group','displayName':'Demo'}
            self.assertTrue(path.startswith('threads/group/messages?limit=50'))
            page=int(path.split('&cursor=')[-1]) if '&cursor=' in path else 0
            start=page*50
            return {'items':rows[start:start+50],'nextCursor':str(page+1) if start+50<len(rows) else None}
        return Mock(request=Mock(side_effect=request),writable=Mock(return_value=True))
    def model(self):return {'choices':[{'message':{'content':'## 主要结论\n驱动调试中，负责人未明确。'}}]}

    def test_all_paginates_past_previous_500_message_cap_and_only_reads(self):
        connection=self.connection(self.rows)
        with patch('api_diagnostics.request',return_value=self.model()):
            result=chat_report.run(self.root,self.config,connection,'group','all')
        self.assertEqual(result['count'],620)
        self.assertGreater(connection.request.call_count,11)
        self.assertTrue(Path(result['path']).exists())
        self.assertFalse(list((self.root/'private-data').glob('report-work-*')))
    def test_count_is_exact_without_artificial_ceiling(self):
        with patch('api_diagnostics.request',return_value=self.model()):
            result=chat_report.run(self.root,self.config,self.connection(self.rows),'group','count',count=603)
        self.assertEqual(result['count'],603)
    def test_date_range_includes_end_day_and_excludes_wrong_thread(self):
        rows=[self.row(1),dict(self.row(2),createdAt='2026-01-16T12:00:00+00:00'),dict(self.row(3),threadId='other')]
        with patch('api_diagnostics.request',return_value=self.model()):
            result=chat_report.run(self.root,self.config,self.connection(rows),'group','date','2026-01-15','2026-01-15')
        self.assertEqual(result['count'],1)
    def test_cancellation_and_cursor_cycles_never_create_complete_report(self):
        with patch('api_diagnostics.request') as model:
            with self.assertRaisesRegex(ValueError,'取消'):
                chat_report.run(self.root,self.config,self.connection(self.rows),'group','all',cancel=lambda:True)
            model.assert_not_called()
        connection=Mock(writable=Mock(return_value=True))
        connection.request.side_effect=[{'id':'group'}, {'items':[self.row(1)],'nextCursor':'same'},{'items':[self.row(1)],'nextCursor':'same'}]
        with self.assertRaisesRegex(ValueError,'游标重复'):
            chat_report.run(self.root,self.config,connection,'group','all')
        self.assertFalse(list((self.root/'private-data').glob('chat-reports/*.md')))
    def test_long_messages_are_split_without_truncating_tail(self):
        body='A'*27000+'THE-END-MARKER'
        with patch('api_diagnostics.request',return_value=self.model()) as model:
            result=chat_report.run(self.root,self.config,self.connection([self.row(1,body)]),'group','all')
        self.assertGreater(result['batches'],1)
        self.assertTrue(any('THE-END-MARKER' in call.args[2]['messages'][1]['content'] for call in model.call_args_list))
    def test_short_history_is_reported_and_ai_error_leaves_no_report(self):
        with patch('api_diagnostics.request',return_value=self.model()):
            result=chat_report.run(self.root,self.config,self.connection([self.row(1)]),'group','count',count=99999999)
        self.assertIn('少于请求数量',result['text'])
        with patch('api_diagnostics.request',side_effect=ValueError('provider unavailable')):
            with self.assertRaises(ValueError):chat_report.run(self.root,self.config,self.connection([self.row(1)]),'group','all')
        self.assertEqual(len(list((self.root/'private-data/chat-reports').glob('*.md'))),1)

    def test_large_summaries_are_merged_in_bounded_rounds(self):
        def summarize(config,url,payload):
            text=payload['messages'][1]['content']
            body='摘要'*1800 if text.startswith('\n消息ID') else '合并后的摘要'
            return {'choices':[{'message':{'content':body}}]}
        with patch('api_diagnostics.request',side_effect=summarize) as model:
            result=chat_report.run(self.root,self.config,self.connection([self.row(1,'内容'*70000)]),'group','all')
        self.assertGreater(result['batches'],10)
        self.assertIn('合并后的摘要',result['text'])
        self.assertTrue(all(len(call.args[2]['messages'][1]['content'])<25000 for call in model.call_args_list))

    def test_missing_group_sender_and_direction_do_not_crash_report(self):
        rows=[dict(self.row(1),senderId=None,direction=None),dict(self.row(2),senderId='',direction='incoming'),dict(self.row(3),createdAt=None)]
        with patch('api_diagnostics.request',return_value=self.model()):
            result=chat_report.run(self.root,self.config,self.connection(rows),'group','all')
        self.assertEqual(result['count'],2)
        self.assertTrue(Path(result['path']).exists())
