import json,time,unittest
from unittest.mock import patch
from conversation_style import analyze

class StyleLearningTests(unittest.TestCase):
    def test_only_confirmed_owner_messages_define_style(self):
        data={'account':'a','thread':'friend','createdAt':time.time(),'rows':[{'id':'mine','direction':'outgoing','body':'行 到了喊我'},{'id':'bot','direction':'outgoing','body':'您好，很高兴为您服务'},{'id':'other','direction':'incoming','body':'快到了'}]}
        response={'choices':[{'message':{'content':json.dumps({'style':'短句、少用敬语，结合具体事情接话。','evidence':['mine']})}}]}
        with patch('api_diagnostics.settings',return_value={'endpoint':'http://localhost/v1/chat/completions','model':'test'}),patch('api_diagnostics.request',return_value=response) as request:
            result=analyze({'account':'a','endpoint':'http://localhost','model':'test'},data,['mine'])
        self.assertEqual(result['samples'],1)
        payload=request.call_args.args[2]['messages'][1]['content']
        self.assertNotIn('您好',payload)
        self.assertIn('快到了',payload)
    def test_invalid_evidence_and_stale_previews_cannot_apply(self):
        data={'account':'a','thread':'friend','createdAt':0,'rows':[]}
        with self.assertRaises(ValueError):analyze({'account':'a','endpoint':'http://localhost','model':'test'},data,[])
        data.update(createdAt=time.time(),rows=[{'id':'mine','direction':'outgoing','body':'嗯'}])
        response={'choices':[{'message':{'content':json.dumps({'style':'规则','evidence':['other']})}}]}
        with patch('api_diagnostics.settings',return_value={'endpoint':'http://localhost','model':'test'}),patch('api_diagnostics.request',return_value=response):
            with self.assertRaises(ValueError):analyze({'account':'a','endpoint':'http://localhost','model':'test'},data,['mine'])

    def test_large_selection_is_fully_batched_and_credentials_are_redacted(self):
        from conversation_style import redact
        rows=[{'id':'mine%s'%i,'direction':'outgoing','body':'普通聊天内容'*1800+(' sk-testsecretvalue12345' if i==0 else '')} for i in range(4)]
        data={'account':'a','thread':'friend','createdAt':time.time(),'rows':rows}
        seen=set()
        def respond(config,url,payload):
            value=json.loads(payload['messages'][1]['content'])
            self.assertNotIn('sk-testsecretvalue12345',payload['messages'][1]['content'])
            if 'speaker' in value[0]:
                ids=[r['id'] for r in value if r['speaker']=='我'];seen.update(ids)
            else:ids=[x for r in value for x in r['evidence']]
            return {'choices':[{'message':{'content':json.dumps({'style':'自然短句，不固定口头禅。','evidence':ids[:2]})}}]}
        with patch('api_diagnostics.settings',return_value={'endpoint':'http://localhost','model':'test'}),patch('api_diagnostics.request',side_effect=respond):
            result=analyze({'account':'a','endpoint':'http://localhost','model':'test'},data,[r['id'] for r in rows])
        self.assertEqual(result['samples'],4)
        self.assertGreater(result['batches'],1)
        self.assertEqual(seen,{r['id'] for r in rows})
        self.assertNotIn('sk-testsecretvalue12345',redact('API Key: sk-testsecretvalue12345'))
