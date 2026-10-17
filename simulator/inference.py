"""Strict, bounded OpenAI-compatible tool calls. Never switches to a demo policy."""
import concurrent.futures
import json
import os
import math
import time
import urllib.error
import urllib.request
from .common import uid,canonical

MODELS={'nemotron':'nvidia/nemotron-3.5-super-vl','gemma':'google/gemma-4-31b-it','gemini':'google/gemini-3.1-pro-preview'}
PROMPT='''You control a simulated orchard robot. Use only provided observations and calibrated images. Execute observe, act, measure, verify. Never claim success from an image alone. Keep resources above reserve, inspect again after every attempt, and service observed jams. Never guess that unseen targets are absent. For a wrist view, robot movement changes image coordinates: capture and scan current geometry. Inspect both finger faces and the central stem. Approach with open jaws, assess alignment, close with sufficient force (root extraction needs at least 26 N), capture, and confirm measured contact and positive load before lifting. After a slip, reopen, observe, reposition, reassess, and regrasp. Extract with a vertical lift of at least .18 m, carry above the bin and release. Capture after collection, return, then verify. Hidden target coordinates are unavailable except in the explicitly labeled known diagnostic. Use one choose_action call. Arguments must match the tool requirements provided.'''
TOOLS=[dict(type='function',function=dict(name='choose_action',description='Choose one permitted simulation action',parameters=dict(type='object',properties=dict(action=dict(type='string'),arguments=dict(type='object'),rationale=dict(type='string')),required=['action','arguments'],additionalProperties=False)))]
TOOL_HELP={
 'capture_image':{},'approach':{},'read_moisture':{},'read_flow':{},'aim_nozzle':{'u':'0..1','v':'0..1','frame_id':'current frame id'},
 'dispense':{'liters':'.01..5','frame_id':'current frame id'},'select_tool':{'tool':'nozzle/gripper/fertilizer/vacuum'},
 'remove_weed':{'u':'0..1','v':'0..1','frame_id':'current frame id'},'remove_pest':{'u':'0..1','v':'0..1','frame_id':'current frame id'},
 'read_prescription':{},'read_application':{},'fertilize':{'grams':'.01..5, no greater than remaining prescription','frame_id':'current frame id'},
 'next_stage':{},'service_tool':{},'move_arm':{'pose':'[x,y,z,rx,ry,rz] world meters (y UP), XYZ Euler degrees. Position is jaw CONTACT CENTER, not surface or fingertip. Upright stem grasp center y=0.15 m, valid 0.09..0.22 m. Infer x,z from RGB and consistent non-ground/non-robot surfaces; never copy a ground/leaf y. Alternatively joints:[six joint degrees]'},
 'set_gripper':{'opening':'0..0.12 meters','force':'0..45 newtons'},'open_gripper':{},
 'scan_lidar':{'u':'0..1','v':'0..1','span':'.04..0.5','frame_id':'current frame id'},'measure_depth':{'u':'0..1','v':'0..1','frame_id':'current frame id'},
 'project_ground':{'u':'0..1','v':'0..1','frame_id':'current frame id'},'assess_alignment':{'frame_id':'current frame id','stem_between_fingers':'boolean','depth_consistent':'boolean','evidence':'8..600 characters'},
 'confirm_contact':{'frame_id':'current frame id','evidence':'8..600 characters'},'verify':{},'return':{},'stop':{}
}

class InferenceError(RuntimeError):
    def __init__(self,message,metrics=None):
        super().__init__(message);self.metrics=metrics


def parse_response(response,tool_name='choose_action',allowed_actions=None):
    try:
        choices=response['choices']
        if len(choices)!=1: raise ValueError()
        calls=choices[0]['message']['tool_calls']
        if len(calls)!=1 or calls[0]['type']!='function' or calls[0]['function']['name']!=tool_name: raise ValueError()
        parsed=json.loads(calls[0]['function']['arguments'],parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if tool_name=='treatment_action':
            if not isinstance(parsed,dict) or set(parsed)-set(ARGUMENT_FIELDS)-{'action','reason','x','y','z','rx','ry','rz'}:raise ValueError()
            action=parsed.pop('action',None);reason=parsed.pop('reason',None)
            if not isinstance(reason,str) or len(reason)>1200 or action not in allowed_actions:raise ValueError()
            if action=='move_arm' and 'joints' not in parsed:
                parsed['pose']=[parsed.pop(k) for k in ('x','y','z','rx','ry','rz')]
            parsed=dict(action=action,arguments=parsed,rationale=reason)
        if not isinstance(parsed,dict) or set(parsed)-{'action','arguments','rationale'} or not isinstance(parsed.get('action'),str) or not isinstance(parsed.get('arguments'),dict): raise ValueError()
        if 'rationale' in parsed and (not isinstance(parsed['rationale'],str) or len(parsed['rationale'])>1200): raise ValueError()
        return parsed
    except (KeyError,TypeError,ValueError,IndexError): raise InferenceError('Provider returned an invalid single tool call') from None

class Adapter:
    def __init__(self,engine='crusoe',role='treatment'):
        self.engine=engine; self.role=role
        self.provider='crusoe' if engine=='crusoe' else 'gateway'
        if self.provider=='crusoe':
            self.base=os.getenv('CRUSOE_API_BASE_URL','https://api.inference.crusoecloud.com/v1')
            self.key=os.getenv('CRUSOE_API_KEY',''); self.timeout=25
            default='google/gemma-4-31b-it' if role=='treatment' else 'nvidia/Nemotron-3-Super-120B-A12B' if role in ('orchestrator','verifier','planner','reviewer') else 'nvidia/Nemotron-3-Nano-30B-A3B'
            env='CRUSOE_VISION_MODEL' if role=='treatment' else 'CRUSOE_ORCHESTRATOR_MODEL' if role in ('orchestrator','verifier','planner','reviewer') else 'CRUSOE_WORKER_MODEL'
            self.model=os.getenv(env,os.getenv(env.lower(),default))
            # Canonical IDs returned by this provider's /models inventory (2026-10-17).
            self.model={
                'nvidia/Nemotron-3-Super-120B-A12B':'nvidia/NVIDIA-Nemotron-3-Super-120B-A12B',
                'nvidia/Nemotron-3-Nano-30B-A3B':'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
            }.get(self.model,self.model)
        else:
            self.base=os.getenv('AI_GATEWAY_BASE_URL','https://ai-gateway.vercel.sh/v1'); self.key=os.getenv('AI_GATEWAY_API_KEY') or os.getenv('AI_GATEWAY_KEY',''); self.timeout=55
            self.model=os.getenv(engine.upper()+'_MODEL',MODELS.get(engine,MODELS['gemini']))

    def call(self,observation,image=None,prompt=PROMPT):
        if not self.key: raise InferenceError(f'{self.provider} credential missing')
        content=[dict(type='text',text=canonical(observation))]
        if image:
            for png in (image if isinstance(image,list) else [image])[:3]: content.append(dict(type='image_url',image_url={'url':png}))
        flat=observation.get('trial')=='fieldcrew'
        tool_name='treatment_action' if flat else 'choose_action'
        schema=TOOLS
        if flat:
            fields={k:v for k,v in ARGUMENT_FIELDS.items() if k!='pose'}
            fields.update({k:dict(type='number') for k in ('x','y','z','rx','ry','rz')})
            fields.update(action=dict(type='string',enum=observation['available_actions']),reason=dict(type='string'))
            schema=[dict(type='function',function=dict(name=tool_name,description='Execute one available action. move_arm requires x,y,z,rx,ry,rz. set_gripper requires opening and force. Assess/confirm require current frame_id and evidence.',parameters=dict(type='object',properties=fields,required=['action','reason'],additionalProperties=False)))]
        body=dict(model=self.model,messages=[dict(role='system',content=prompt),dict(role='user',content=content)],tools=schema,tool_choice='required' if flat else {'type':'function','function':{'name':tool_name}},temperature=.1,max_tokens=4096)
        request=urllib.request.Request(self.base.rstrip('/')+'/chat/completions',data=canonical(body).encode(),headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        started=time.monotonic(); response=None
        try:
            with urllib.request.urlopen(request,timeout=self.timeout) as result: response=json.loads(result.read(2*1024*1024))
        except urllib.error.HTTPError as exc:
            raise InferenceError(f'{self.provider} HTTP {exc.code}; no fallback performed',self.failed_metrics(started)) from None
        except (OSError,ValueError):
            raise InferenceError(f'{self.provider} unavailable or timed out',self.failed_metrics(started)) from None
        envelope_valid=isinstance(response,dict)
        response=response if envelope_valid else {}
        raw_usage=response.get('usage')
        envelope_valid=envelope_valid and (raw_usage is None or isinstance(raw_usage,dict))
        usage=raw_usage if isinstance(raw_usage,dict) else {}
        envelope_valid=envelope_valid and all(type(usage[k]) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens') if k in usage)
        cost=reported_cost(usage)
        try:
            if not envelope_valid:raise InferenceError('Provider returned an invalid response envelope')
            decision=parse_response(response,tool_name,observation.get('available_actions'))
        except InferenceError as exc:
            exc.metrics=self.failed_metrics(started);exc.metrics['usage']={k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0}
            exc.metrics.update(cost=cost,response_id=response.get('id'),returned_model=response.get('model'))
            choices=response.get('choices')
            exc.metrics['response_summary']=[dict(finish_reason=c.get('finish_reason')) for c in choices[:2] if isinstance(c,dict)] if isinstance(choices,list) else []
            raise

        return dict(id=uid(),decision=decision,requested_model=self.model,returned_model=response.get('model'),provider=self.provider,response_id=response.get('id'),usage={k:usage[k] for k in ('prompt_tokens','completion_tokens','total_tokens') if k in usage},cost=cost,latency=time.monotonic()-started)

    def failed_metrics(self,started):
        return dict(id=uid(),status='failed',requested_model=self.model,returned_model=None,provider=self.provider,response_id=None,usage={},cost=None,latency=time.monotonic()-started)

def reported_cost(usage):
    details=usage.get('cost_details');details=details if isinstance(details,dict) else {}
    values=[usage.get('cost'),details.get('upstream_inference_cost')]
    if values[0] is None: return None
    try:
        numbers=[float(v) for v in values if v is not None]
        return sum(numbers) if all(math.isfinite(v) and v>=0 for v in numbers) else None
    except (TypeError,ValueError): return None

# Explicit argument fields are essential for providers that compile object schemas;
# an unspecified object may be interpreted as an empty object by a schema adapter.
ARGUMENT_FIELDS={
    'u':{'type':'number','minimum':0,'maximum':1},'v':{'type':'number','minimum':0,'maximum':1},
    'span':{'type':'number','minimum':.04,'maximum':.5},'frame_id':{'type':'string'},
    'liters':{'type':'number','minimum':.01,'maximum':5},'grams':{'type':'number','minimum':.01,'maximum':5},
    'tool':{'type':'string'},'opening':{'type':'number','minimum':0,'maximum':.12},'force':{'type':'number','minimum':0,'maximum':45},
    'pose':{'type':'array','items':{'type':'number'},'minItems':6,'maxItems':6},
    'joints':{'type':'array','items':{'type':'number'},'minItems':6,'maxItems':6},
    'stem_between_fingers':{'type':'boolean'},'depth_consistent':{'type':'boolean'},'evidence':{'type':'string'},
    'row':{'type':'integer'},'vehicle':{'type':'string'},'ownership_version':{'type':'integer'},'zone':{'type':'string'},'target':{'type':'string'},
    'diagnosis':{'type':'string'},'hypothesis':{'type':'string'},'prompt':{'type':'string'}
}
TOOLS[0]['function']['parameters']['properties']['arguments'].update(properties=ARGUMENT_FIELDS,additionalProperties=False)
