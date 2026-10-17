import concurrent.futures
import time
import unittest
from unittest.mock import patch
from simulator.engine import Mission
from simulator.telemetry import Telemetry
from simulator.runtime import Runtime


class TelemetryShowcaseTests(unittest.TestCase):
    def test_health_and_incidents_are_code_computed_and_deduplicated(self):
        w=Mission(rows=0);w.status='running';t=Telemetry();t.sample(w,0,True,{'W1':'inference_wait'})
        health=t.health(t.last_heartbeat)
        self.assertEqual(health['W1']['status'],'healthy_wait');self.assertEqual(health['W2']['status'],'healthy')
        self.assertEqual(t.health(t.last_heartbeat+6)['W2']['status'],'stale_heartbeat')
        t.note_command('W3',False);t.note_command('W3',False);t.note_command('W3',False)
        self.assertEqual(t.health(t.last_heartbeat)['W3']['status'],'possible_loop')
        # A breakdown away from the depot needs retrieval; one at the depot is already recovered.
        w.vehicles['W1']['position']=[0,0];w.breakdown('W1');t.sample(w,0,True)
        opened,resolved=t.detect_incidents(w,t.health(t.last_heartbeat))
        self.assertEqual([(i['robot'],i['kind']) for i in opened],[('W1','breakdown'),('W3','possible_loop')])
        self.assertEqual([e['type'] for e in w.events[-2:]],['incident','incident']);self.assertEqual(w.events[-2]['robot_id'],'W1');self.assertEqual(w.events[-2]['payload']['incident_kind'],'breakdown')
        self.assertEqual(t.detect_incidents(w,t.health(t.last_heartbeat)),([],[]))
        self.assertEqual(t.health(t.last_heartbeat)['W1']['open_incidents'],[opened[0]['id']])
        w.vehicles['W1']['recovered']=True;t.sample(w,0,True)
        opened,resolved=t.detect_incidents(w,t.health(t.last_heartbeat))
        self.assertEqual([i['kind'] for i in resolved],['breakdown']);self.assertEqual(w.events[-1]['type'],'incident_resolved')
        self.assertEqual(list(t.incidents),[('W3','possible_loop')])

    def test_query_is_bounded_and_non_physical(self):
        w=Mission(rows=0);w.status='running';t=Telemetry()
        for i in range(200): w.time=float(i);t.sample(w,0,True)
        revision,decisions=w.revision,len(w.receipts)
        answer=t.query('W1',since_sim_time=50)
        self.assertEqual(answer['samples'],150);self.assertLessEqual(answer['returned'],60);self.assertEqual(answer['rows'][0]['sim_time'],50.0)
        self.assertEqual(answer['rows'][-1]['sim_time'],199.0);self.assertIn('battery_delta',answer)
        self.assertEqual((w.revision,len(w.receipts)),(revision,decisions))
        self.assertEqual(t.query('R9')['samples'],0)

    def test_live_orchestrator_sees_incidents_queries_history_and_escalates(self):
        class FakeAdapter:
            calls=[];script=[]
            def __init__(self,engine,role):self.role=role;self.model='fake';self.base='https://example.invalid'
            def call(self,obs,*args):
                FakeAdapter.calls.append((self.role,obs))
                if self.role=='planner':return dict(decision={'action':'accept_contract','arguments':{}},usage={},cost=None)
                if self.role=='orchestrator' and FakeAdapter.script:return dict(decision=FakeAdapter.script.pop(0),usage={},cost=None)
                return dict(decision=obs['feasible_options'][0],usage={},cost=None)
        w=Mission();w.status='running'
        with patch('threading.Thread.start'),patch.object(Runtime,'persist',return_value=True):
            r=Runtime(world=w,config={'mode':'live','engine':'crusoe','speed':8})
        self.addCleanup(r.close)
        class Immediate:
            def submit(self,fn,*args):f=concurrent.futures.Future();f.set_result(fn(*args));return f
            def shutdown(self,**kwargs):pass
        r.executor.shutdown(wait=False);r.executor=Immediate()
        with patch('simulator.runtime.Adapter',FakeAdapter),patch.object(Runtime,'persist',return_value=True):
            r._live();r._live();r._live()   # planner accepts, first assignment is dispatched and applied
            self.assertTrue(w.planned);self.assertTrue(w.assignments)
            w.vehicles['W1']['position']=[0,0];w.breakdown('W1');r.telemetry.sample(w,0,True);r.monitor(time.monotonic())
            incident=w.events[-1];self.assertEqual(incident['type'],'incident');self.assertTrue(r.incident_alert)
            # The model names the decision in the action and gives no incident_id; the only open incident and its rationale complete the response.
            FakeAdapter.script=[{'action':'query_telemetry','arguments':{'robot':'W1','since_sim_time':0}},
                                {'action':'incident_escalate','arguments':{'target':'W1'},'rationale':'W1 is down mid-row; operator should confirm retrieval'}]
            r._live()
            role,permitted=FakeAdapter.calls[-1];self.assertEqual(role,'orchestrator')
            self.assertEqual(permitted['observation']['open_incidents'][0]['kind'],'breakdown')
            self.assertEqual(permitted['observation']['fleet_health']['W1']['status'],'disabled')
            self.assertTrue({o['action'] for o in permitted['feasible_options']}>={'incident_retrieve','incident_escalate','query_telemetry'})
            self.assertEqual(next(o['arguments'] for o in permitted['feasible_options'] if o['action']=='incident_escalate'),{'incident_id':incident['payload']['id'],'incident_robot':'W1'})
            self.assertFalse(r.incident_alert)
            r._live()
            self.assertEqual([e['payload']['returned'] for e in w.events if e['type']=='telemetry_query'],[1])
            role,permitted=FakeAdapter.calls[-1];self.assertEqual(role,'orchestrator')
            self.assertGreaterEqual(permitted['telemetry_query_result']['samples'],1);self.assertEqual(permitted['telemetry_query_result']['robot'],'W1')
            r._live()
            self.assertEqual(w.status,'paused');self.assertEqual(r.escalation['robot'],'W1')
            self.assertEqual([e['type'] for e in w.events if e['type'] in ('incident_response','escalation')],['incident_response','escalation'])
            self.assertEqual(r.telemetry.incidents[('W1','breakdown')]['response'],dict(decision='escalate',reason='W1 is down mid-row; operator should confirm retrieval',by='orchestrator',wall_utc=r.telemetry.incidents[('W1','breakdown')]['response']['wall_utc']))
            self.assertEqual(r.snapshot()['incidents']['open'][0]['response']['decision'],'escalate')

    def test_incident_id_is_resolved_only_when_unambiguous(self):
        from simulator.inference import InferenceError
        w=Mission(rows=0);w.status='running'
        with patch('threading.Thread.start'),patch.object(Runtime,'persist',return_value=True):
            r=Runtime(world=w,config={'mode':'live','engine':'crusoe','speed':8})
        self.addCleanup(r.close)
        for robot in ('W1','W2'): w.vehicles[robot]['position']=[0,0];w.breakdown(robot)
        r.telemetry.sample(w,0,True);r.monitor(time.monotonic())
        self.assertEqual(sorted(r.telemetry.incidents),[('W1','breakdown'),('W2','breakdown')])
        with self.assertRaisesRegex(InferenceError,'needs incident_id'):r.orchestrator_tool('orchestrator','respond_incident',dict(decision='retrieve',reason='send R1'))
        with self.assertRaisesRegex(InferenceError,'needs incident_id'):r.orchestrator_tool('orchestrator','respond_incident',dict(decision='retrieve',reason='send R1',target='W5'))
        with self.assertRaisesRegex(InferenceError,'needs incident_id'):r.orchestrator_tool('orchestrator','respond_incident',dict(decision='retrieve',reason='W1 and W2 are both down',target='W5'))
        # The helper vehicle in `target` is not the incident; the one robot the reason names is.
        r.orchestrator_tool('orchestrator','respond_incident',dict(decision='retrieve',reason='W2 is disabled with drive failure; retrieve it using spare W5',target='W5'))
        self.assertEqual(r.telemetry.incidents[('W2','breakdown')]['response']['decision'],'retrieve');self.assertIsNone(r.telemetry.incidents[('W1','breakdown')]['response'])
        self.assertEqual(w.status,'running')

    def test_fleet_roles_use_a_typed_flat_schema_with_an_action_enum(self):
        import json
        from simulator.inference import Adapter,parse_response,InferenceError
        permitted=dict(observation={},role='orchestrator',robot='orchestrator',feasible_options=[dict(action='activate_spare',arguments={}),dict(action='respond_incident',arguments=dict(incident_id='abc',decision='retrieve',reason='why'))])
        captured={}
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='respond_incident',reason='W1 is down; send R1',incident_id='abc',decision='retrieve',row=0,vehicle='',target=''))}}]}}],'usage':{'total_tokens':5}}).encode()
        def urlopen(request,timeout=None):captured['body']=json.loads(request.data);return Reply()
        a=Adapter('crusoe','orchestrator');a.key='fake'
        with patch('urllib.request.urlopen',urlopen):result=a.call(permitted)
        tool=captured['body']['tools'][0]['function'];self.assertEqual(tool['name'],'fleet_action');self.assertEqual(captured['body']['tool_choice'],'required')
        self.assertEqual(tool['parameters']['properties']['action']['enum'],['activate_spare','respond_incident']);self.assertIn('incident_id',tool['parameters']['properties'])
        # Empty defaults are dropped; the zero row is a real integer and stays (it is ignored by actions that do not read it).
        self.assertEqual(result['decision'],dict(action='respond_incident',arguments=dict(incident_id='abc',decision='retrieve',row=0),rationale='W1 is down; send R1'))
        bad={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='assign',reason='x',diagnosis='junk'))}}]}}]}
        with self.assertRaises(InferenceError):parse_response(bad,'fleet_action',['assign'])
        with self.assertRaises(InferenceError):parse_response({'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='stop',reason='x'))}}]}}]},'fleet_action',['assign'])

    def test_repeated_identical_calls_collapse_and_omitted_option_fields_are_copied(self):
        import json
        from simulator.inference import parse_response,InferenceError
        call={'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='inspect',reason='Inspect zone 1:2',zone='1:2'))}}
        repeated={'choices':[{'message':{'tool_calls':[dict(call,id=str(i)) for i in range(5)]},'finish_reason':'length'}]}
        self.assertEqual(parse_response(repeated,'fleet_action',['inspect'])['arguments'],{'zone':'1:2'})
        reworded={'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='inspect',reason='Initial zone inspection as requested',zone='1:2'))}}
        self.assertEqual(parse_response({'choices':[{'message':{'tool_calls':[call,reworded]}}]},'fleet_action',['inspect'])['rationale'],'Inspect zone 1:2')
        # Repeats that drift by adding a field still name one decision; a repeat that changes a value does not.
        fuller={'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='inspect',reason='again',zone='1:2',ownership_version=4))}}
        self.assertEqual(parse_response({'choices':[{'message':{'tool_calls':[call,fuller,call]}}]},'fleet_action',['inspect'])['arguments'],{'zone':'1:2','ownership_version':4})
        conflicting={'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='inspect',reason='x',zone='1:2',ownership_version=5))}}
        with self.assertRaises(InferenceError):parse_response({'choices':[{'message':{'tool_calls':[fuller,conflicting]}}]},'fleet_action',['inspect'])
        other={'type':'function','function':{'name':'fleet_action','arguments':json.dumps(dict(action='inspect',reason='x',zone='1:1'))}}
        with self.assertRaises(InferenceError):parse_response({'choices':[{'message':{'tool_calls':[call,other]}}]},'fleet_action',['inspect'])
        w=Mission(rows=0);w.status='running'
        with patch('threading.Thread.start'),patch.object(Runtime,'persist',return_value=True):
            r=Runtime(world=w,config={'mode':'live','engine':'crusoe','speed':8})
        self.addCleanup(r.close)
        r.offered['W2']=[dict(action='inspect',arguments=dict(zone='1:2',ownership_version=3)),dict(action='inspect',arguments=dict(zone='1:1',ownership_version=3)),dict(action='return',arguments={})]
        self.assertEqual(r.complete_arguments('W2',dict(action='inspect',arguments={'zone':'1:2'})),{'zone':'1:2','ownership_version':3})
        self.assertEqual(r.complete_arguments('W2',dict(action='inspect',arguments={})),{})   # two candidates: nothing is guessed
        self.assertEqual(r.complete_arguments('W2',dict(action='inspect',arguments={'zone':'9:9','row':1})),{'zone':'9:9'})
        self.assertEqual(r.complete_arguments('W2',dict(action='water',arguments={'zone':'1:2','robot':'W2'})),{'zone':'1:2'})
        # Stray typed fields (robot, decision, row) can never reach the engine's keyword boundary.
        self.assertEqual(r.complete_arguments('W2',dict(action='inspect',arguments={'zone':'1:2','robot':'W2','decision':'continue','row':3})),{'zone':'1:2','ownership_version':3})

    def test_query_streak_and_worker_misuse_are_bounded(self):
        w=Mission(rows=0);w.status='running'
        with patch('threading.Thread.start'),patch.object(Runtime,'persist',return_value=True):
            r=Runtime(world=w,config={'mode':'live','engine':'crusoe','speed':8})
        self.addCleanup(r.close)
        from simulator.inference import InferenceError
        for _ in range(3): r.orchestrator_tool('orchestrator','query_telemetry',{'robot':'W1','since_sim_time':0})
        with self.assertRaisesRegex(InferenceError,'repeated telemetry queries'):r.orchestrator_tool('orchestrator','query_telemetry',{'robot':'W1'})
        with self.assertRaisesRegex(InferenceError,'orchestrator tool'):r.orchestrator_tool('W2','respond_incident',{})
        with self.assertRaisesRegex(InferenceError,'unknown or already resolved'):r.orchestrator_tool('orchestrator','respond_incident',{'incident_id':'nope','decision':'continue','reason':'x'})
