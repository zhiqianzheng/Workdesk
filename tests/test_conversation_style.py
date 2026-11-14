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
