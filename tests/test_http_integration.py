import http.client
import json
import os
import unittest
from simulator.common import load_env

@unittest.skipUnless(os.getenv('WALLNE_HTTP')=='1','requires running loopback app')
class HttpIntegration(unittest.TestCase):
    def request(self,path,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',8765,timeout=30);c.request('GET',path,headers=headers or {});r=c.getresponse();body=r.read();status=r.status;c.close();return status,body
    def test_assets_origin_traversal_and_secret_free_exports(self):
        for path in ('/','/treatment.html','/sessions.html','/vendor/three.module.js','/vendor/ez-tree/ez-tree.es.js'):
            self.assertEqual(self.request(path)[0],200,path)
        for path in ('/../.env','/%2e%2e/.env','/vendor/../.env','/.env'):
            self.assertIn(self.request(path)[0],(400,404),path)
        self.assertEqual(self.request('/api/state',{'Host':'evil.example'})[0],400)
        self.assertEqual(self.request('/api/state',{'Origin':'https://evil.example'})[0],400)
        load_env()
        for path in ('/api/export','/api/treatment/export'):
            status,raw=self.request(path);self.assertEqual(status,200)
            for key in ('SUPABASE_SECRET_KEY','CRUSOE_API_KEY','AI_GATEWAY_API_KEY','AI_GATEWAY_KEY'):
                value=os.getenv(key)
                if value:self.assertNotIn(value.encode(),raw)
