import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
from api_diagnostics import list_models,test_chat,request
from desktop_app import Platform


class ApiDiagnosticTests(unittest.TestCase):
    def setUp(self):self.data={'endpoint':'https://example.test/v1','model':'model','apiKey':'synthetic'}

    def test_models_are_deduplicated_and_sorted_without_requiring_model_id(self):
        with patch('api_diagnostics.request',return_value={'data':[{'id':'z'},{'id':'a'},{'id':'z'},{'name':'invalid'}]}) as req:
            self.assertEqual(list_models({**self.data,'model':''}),['a','z'])
        self.assertEqual(req.call_args.args[1],'https://example.test/v1/models')

    def test_chat_requires_actual_nonempty_response_and_sends_no_private_chat(self):
        with patch('api_diagnostics.request',return_value={'choices':[{'message':{'content':'OK'}}]}) as req:
            self.assertIn('成功',test_chat(self.data))
        self.assertEqual(req.call_args.args[2]['messages'],[{'role':'user','content':'Reply only OK.'}])
        with patch('api_diagnostics.request',return_value={'choices':[{'message':{'content':''}}]}):
            with self.assertRaises(ValueError):test_chat(self.data)

    def test_report_timeout_is_respected_and_distinct_from_unreachable_network(self):
        with patch('api_diagnostics.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=TimeoutError()
            with self.assertRaisesRegex(ValueError,'180'):
                request({**self.data,'requestTimeout':180},'https://example.test')
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],180)
            opener.return_value.open.side_effect=urllib.error.URLError('network')
            with self.assertRaisesRegex(ValueError,'无法连接'):
                request(self.data,'https://example.test')
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],30)

    def test_errors_do_not_echo_provider_body_or_key(self):
        for code in [401,403,404,429,500]:
            with patch('api_diagnostics.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect=urllib.error.HTTPError('https://example.test',code,'secret body',{},None)
                with self.assertRaises(ValueError) as error:request(self.data,'https://example.test')
                self.assertNotIn('synthetic',str(error.exception));self.assertNotIn('secret body',str(error.exception))

    def test_missing_models_endpoint_does_not_report_chat_unusable(self):
        with patch('api_diagnostics.request',return_value={'anything':'else'}):
            with self.assertRaisesRegex(ValueError,'手动填写'):list_models(self.data)

    def test_saved_key_cannot_be_sent_to_new_provider_by_blank_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'private-data';p.mkdir()
            (p/'workdesk-native-ai.json').write_text(json.dumps({'encryptedKey':'reference','endpoint':'https://old.test/v1/chat/completions'}))
            app=Platform(root=tmp,runtime=tmp)
            with patch('api_diagnostics.protect') as decrypt:
                with self.assertRaisesRegex(ValueError,'地址已变更'):app.api_check({**self.data,'apiKey':''})
            decrypt.assert_not_called()
