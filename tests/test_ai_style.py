import json
import unittest
from unittest.mock import patch, MagicMock

from ai_reply import generate
from ai_style import CHAT_STYLE
from ai_web import web_payload


class StyleIntegrationTests(unittest.TestCase):
    def test_chat_and_responses_receive_style_and_context(self):
        config = dict(model='test', endpoint='http://localhost/v1/chat/completions',
                      apiKey='', style='简短', webSearch=False, mediaReplies=False)
        records = [dict(direction='incoming', kind='text', text='驱动还没起来')]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            'choices': [{'finish_reason': 'stop', 'message': {'content': '报什么错？'}}]
        }).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch('ai_reply.urllib.request.build_opener', return_value=opener):
            self.assertEqual(generate(config, records), '报什么错？')
        payload = json.loads(opener.open.call_args.args[0].data)
        self.assertIn(CHAT_STYLE, payload['messages'][0]['content'])
        self.assertEqual(payload['messages'][-1]['content'], '驱动还没起来')
        config['webSearch'] = True
        with patch('ai_web.generate_with_search', return_value='报什么错？') as searched:
            generate(config, records)
        forwarded = web_payload(config, searched.call_args.args[1])
        self.assertIn(CHAT_STYLE, forwarded['instructions'])
        self.assertIn('必须先使用 web_search', forwarded['instructions'])
        self.assertEqual(forwarded['input'][-1]['content'], '驱动还没起来')


if __name__ == '__main__':
    unittest.main()
