import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/'operations/qwen-stack-20260922/check_endpoint.py'
spec=importlib.util.spec_from_file_location('endpoint',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class EndpointTests(unittest.TestCase):
    def test_defaults_and_override(self):
        settings={'defaultProvider':'local-qwen','defaultModel':'flash'}
        self.assertEqual(m.selected([],settings),('local-qwen','flash'))
        self.assertEqual(m.selected(['--model','v100/other'],settings),('v100','other'))
    def test_only_selected_endpoint(self):
        calls=[]
        providers={'qwen':{'baseUrl':'http://local.invalid/v1','models':[{'id':'flash','contextWindow':131072,'maxTokens':16384}]},'unavailable':{}}
        def request(url,headers):
            calls.append(url);return {'data':[{'id':'flash','context_length':131072}]}
        self.assertEqual(m.validate('qwen','flash',providers,request)['context'],131072)
        self.assertEqual(calls,['http://local.invalid/v1/models'])
    def test_mismatch_fails(self):
        providers={'qwen':{'baseUrl':'http://local.invalid/v1','models':[{'id':'flash','contextWindow':131072}]}}
        with self.assertRaises(ValueError):m.validate('qwen','flash',providers,lambda *_:{'data':[{'id':'flash','context_length':32768}]})
        with self.assertRaises(ValueError):m.validate('qwen','flash',providers,lambda *_:{'data':[{'id':'other'}]})

if __name__=='__main__':unittest.main()
