import copy
import unittest
from simulator.inference import parse_response,InferenceError
from simulator.review import evaluate_pairs
from simulator.telemetry import Telemetry
from simulator.png import decode

class BoundaryTests(unittest.TestCase):
    def test_strict_tool_call(self):
        response={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'choose_action','arguments':'{"action":"return","arguments":{}}'}}]}}]}
        self.assertEqual(parse_response(response)['action'],'return')
        for invalid in ({},dict(response,choices=[]),{'choices':[{'message':{'tool_calls':response['choices'][0]['message']['tool_calls']*2}}]}):
            with self.assertRaises(InferenceError):parse_response(invalid)
        response['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"action":"return","arguments":{"x":NaN}}'
        with self.assertRaises(InferenceError):parse_response(response)

    def test_review_gate_does_not_promote_unknown_cost(self):
        manifest={'scenarios':['a','b','c','d'],'withheld_case':'d'}
        rows=[dict(scenario=s,variant=v,passed=True,commands=10 if v=='baseline' else 5,cost=None,hard_violations=0,regressions_passed=True) for s in manifest['scenarios'] for v in ['baseline','candidate']]
        self.assertFalse(evaluate_pairs(manifest,rows)[0])
        for row in rows:row['cost']=.01
        self.assertTrue(evaluate_pairs(manifest,rows)[0]);rows[-1]['passed']=False;self.assertFalse(evaluate_pairs(manifest,rows)[0])
        rows[-1]['passed']=True;rows[-1]['hard_violations']=1;self.assertFalse(evaluate_pairs(manifest,rows)[0])

    def test_health_wait_is_not_failure(self):
        self.assertEqual(Telemetry.health_status(1,'inference',0),'healthy_wait')
        self.assertEqual(Telemetry.health_status(6,'inference',0),'stale_heartbeat')
        self.assertEqual(Telemetry.health_status(1,None,3),'possible_loop')

    def test_png_rejects_unbounded_and_invalid_input(self):
        for raw in (b'',b'not a png',b'\x89PNG\r\n\x1a\n'+b'0'*3000000):
            with self.assertRaises(ValueError):decode(raw)

    def test_fleet_roles_and_stale_results(self):
        import concurrent.futures
        from unittest.mock import patch
        from simulator.runtime import Runtime
        from simulator.engine import Mission
        class FakeAdapter:
            calls=[]
            def __init__(self,engine,role):self.role=role
            def call(self,obs,*args):
                FakeAdapter.calls.append(self.role)
                if self.role=='planner':d={'action':'accept_contract','arguments':{}}
                elif self.role=='verifier':d={'action':'verify','arguments':{}}
                else:d=obs['feasible_options'][0]
                return dict(decision=d,usage={},cost=None)
        w=Mission(rows=0);w.status='running'
        with patch('threading.Thread.start'),patch.object(Runtime,'persist',return_value=True):
            runtime=Runtime(world=w,config={'mode':'live','engine':'crusoe','speed':8})
        with patch('simulator.runtime.Adapter',FakeAdapter):
            # Resolve mocked role calls synchronously without real network or background physics.
            class Immediate:
                def submit(self,fn,*args):
                    f=concurrent.futures.Future();f.set_result(fn(*args));return f
                def shutdown(self,**kwargs):pass
            runtime.executor.shutdown(wait=False);runtime.executor=Immediate()
            runtime._live();runtime._live();runtime._live()
            self.assertEqual(w.status,'failed' if not all(w.verify().values()) else 'completed')
            self.assertEqual(FakeAdapter.calls,['planner','verifier'])
            previous=len(w.receipts);f=concurrent.futures.Future();f.set_result({'decision':{'action':'activate_spare','arguments':{}},'usage':{},'cost':None})
            runtime.futures['orchestrator']=('another-session',f);runtime._live();self.assertEqual(len(w.receipts),previous)
            runtime.close()
