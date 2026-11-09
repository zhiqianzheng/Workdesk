import unittest
from unittest.mock import patch
from ai_reply import AutoReply, ReplyError, generate
from ai_web import WebSearchError, responses_endpoint, response_text, web_payload


class WebSearchTests(unittest.TestCase):
    def config(self):
        return {'endpoint':'https://example.test/v1/chat/completions', 'model':'test-model',
                'apiKey':'synthetic-key', 'style':'简短', 'contacts':[], 'allContacts':True, 'interval':2}

    def test_web_search_is_opt_in_and_validated(self):
        self.assertFalse(AutoReply.validate(self.config())['webSearch'])
        self.assertTrue(AutoReply.validate({**self.config(), 'webSearch':True})['webSearch'])
        with self.assertRaises(ReplyError):
            AutoReply.validate({**self.config(), 'webSearch':'yes'})

    def test_endpoint_uses_configured_provider(self):
        self.assertEqual(responses_endpoint(self.config()['endpoint']), 'https://example.test/v1/responses')
        with self.assertRaises(WebSearchError):responses_endpoint('https://example.test/unknown')

    def test_payload_enables_live_search_and_keeps_context_roles_and_images(self):
        messages=[{'role':'system','content':'original rules'}, {'role':'assistant','content':'你好'},
                  {'role':'user','content':[{'type':'text','text':'这是什么？'},
                   {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,AA==','detail':'auto'}}]}]
        p=web_payload(self.config(),messages)
        self.assertTrue(p['tools'][0]['external_web_access'])
        self.assertEqual(p['tool_choice'],'auto')
        self.assertIn('original rules',p['instructions'])
        self.assertIn('哪个城市',p['instructions'])
        self.assertEqual(p['input'][0]['role'],'assistant')
        self.assertEqual(p['input'][1]['content'][1]['type'],'input_image')
        self.assertNotIn('synthetic-key',str(p))

    def response(self):
        return {'status':'completed','output':[{'type':'web_search_call','status':'completed'},
            {'type':'message','role':'assistant','content':[{'type':'output_text','text':'今天晴。\ue200cite\ue202source\ue201',
                'annotations':[{'type':'url_citation','url':'https://weather.example/today'}]}]}]}

    def test_citations_become_visible_in_wechat_and_internal_markers_removed(self):
        d={};text=response_text(self.response(),d)
        self.assertIn('https://weather.example/today',text)
        self.assertNotIn('\ue200',text)
        self.assertEqual(d['search_calls'],1)

    def test_existing_citation_link_not_duplicated(self):
        r=self.response();r['output'][1]['content'][0]['text']='来源：https://weather.example/today'
        self.assertEqual(response_text(r).count('https://weather.example/today'),1)

    def test_incomplete_response_is_not_sent_as_finished_answer(self):
        with self.assertRaises(WebSearchError):response_text({'status':'incomplete','output':[]})

    def test_enabled_generate_uses_web_path(self):
        with patch('ai_web.generate_with_search',return_value='查到的最新信息') as web:
            text=generate({**self.config(),'webSearch':True},[{'direction':'incoming','kind':'text','text':'今天天气？'}])
        self.assertEqual(text,'查到的最新信息')
        self.assertTrue(web.called)

    def test_search_failure_does_not_silently_fall_back_to_model_memory(self):
        with patch('ai_web.generate_with_search',side_effect=WebSearchError('search failed')):
            with self.assertRaises(ReplyError):
                generate({**self.config(),'webSearch':True},[{'direction':'incoming','kind':'text','text':'今天新闻'}])


if __name__ == '__main__':unittest.main()
