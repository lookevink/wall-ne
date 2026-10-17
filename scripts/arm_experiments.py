#!/usr/bin/env python3
"""Bounded live experiments through the local API; browser must supply real observations."""
import argparse
import json
import pathlib
import time
import urllib.request
import uuid

BASE='http://127.0.0.1:8765'

def api(route,body=None):
    req=urllib.request.Request(BASE+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)

def trial(engine,condition,seed=7,expected=None):
    started=time.monotonic();session=None
    try:
        state=api('/api/treatment/reset',dict(kind='arm',seed=seed,mode='vision',engine=engine,trial=condition));session=state['id']
        if expected:
            actual=dict(model=state['config']['models']['treatment'],provider_base=state['config']['provider_base'],treatment_code_hash=state['config']['treatment_code_hash'],prompt_version=state['prompt_versions']['treatment'])
            if actual!=expected:raise RuntimeError('frozen repeatability conditions changed before inference')
        api('/api/treatment/start',{})
        while True:
            state=api('/api/treatment/state')
            if state['id']!=session: raise RuntimeError('session replaced externally')
            if state['status'] in ('completed','failed','blocked','aborted','storage_blocked'):break
            cost=state['inference']['cost']
            if time.monotonic()-started>=240 or cost is not None and cost>=1:
                api('/api/treatment/stop',{});state=api('/api/treatment/state');break
            time.sleep(1)
        # Await accounting only. No new actions are allowed after the terminal boundary.
        accounting_deadline=time.monotonic()+60
        while state['inference'].get('pending_calls',0) and time.monotonic()<accounting_deadline:
            time.sleep(.5);state=api('/api/treatment/state')
            if state['id']!=session:raise RuntimeError('session replaced during final accounting')
        path=pathlib.Path('.runtime/exports');path.mkdir(parents=True,exist_ok=True)
        export_error=None
        try: (path/f'{session}.json').write_text(json.dumps(api(f'/api/sessions/{session}/export'),indent=2))
        except Exception: export_error='Export unavailable; authoritative session retained in Supabase'
        return dict(export_error=export_error,session_id=session,engine=engine,trial=condition,seed=seed,status=state['status'],feedback=state.get('feedback'),checks=state['checks'],calls=state['inference']['calls'],failed_calls=state['inference'].get('failed_calls'),pending_calls=state['inference'].get('pending_calls'),inference_seconds=state['inference'].get('latency_seconds'),cost=state['inference']['cost'],model=state['config']['models']['treatment'],provider_routes=state.get('provider_routes',{}),provider_policy=state['config'].get('fallback'),treatment_code_hash=state['config']['treatment_code_hash'],wall_seconds=time.monotonic()-started,controller_progress=state.get('control_progress'),physical_milestones={name:state.get(name) for name in ('holding','extracted','deposited')})
    finally:
        if session:
            try:
                current=api('/api/treatment/state')
                if current['id']==session and current['status']=='running':api('/api/treatment/stop',{})
            except Exception:pass

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group()
    for flag in ('lidar','alignment','wrist'):g.add_argument('--'+flag,action='store_true')
    p.add_argument('--engine',choices=['crusoe','nemotron','gemma','gemini']);p.add_argument('--condition',choices=['baseline','known','depth','lidar','alignment','wrist','fieldcrew']);p.add_argument('--seed',type=int,default=7)
    args=p.parse_args()
    condition=args.condition or next((x for x in ('lidar','alignment','wrist') if getattr(args,x)),None)
    runs=[(args.engine,condition or 'baseline')] if args.engine else [(engine,condition) for engine in ('nemotron','gemma')] if condition else [('gemini','baseline')]+[(engine,'known') for engine in ('gemini','nemotron','gemma')]+[(engine,'depth') for engine in ('nemotron','gemma')]
    results=[]
    try:
        for engine,condition in runs:
            result=trial(engine,condition,args.seed);results.append(result);print(json.dumps(result),flush=True)
    finally:
        path=pathlib.Path('docs/evaluations');path.mkdir(parents=True,exist_ok=True)
        (path/f'arm-{uuid.uuid4()}.json').write_text(json.dumps(results,indent=2))

if __name__=='__main__':main()
