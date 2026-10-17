#!/usr/bin/env python3
"""Run or monitor the main orchard's live five-worker full-care mission."""
import argparse
import json
import pathlib
import time
from scripts.arm_experiments import api


def monitor(session):
    started=time.monotonic();last=None
    while True:
        s=api('/api/state')
        if s['id']!=session:raise RuntimeError('Fleet session replaced externally')
        summary=dict(session_id=session,status=s['status'],feedback=s['feedback'],calls=s['inference']['calls'],failures=s['inference']['failed_calls'],pending=s['inference']['pending_calls'],completed=sum(a['status']=='completed' for a in s['assignments'].values()),assigned=len(s['assignments']),workers={k:dict(phase=w['phase'],status=w['status'],feedback=w['feedback'],calls=w['inference']['calls'],holding=w['holding'],extracted=w['extracted'],water=round(w['moisture'],2)) for k,w in s['care_workers'].items()})
        if summary!=last:print(json.dumps(summary),flush=True);last=summary
        if s['status'] in ('completed','blocked','failed','aborted','storage_blocked'):break
        time.sleep(15)
    deadline=time.monotonic()+65
    while s['inference']['pending_calls'] and time.monotonic()<deadline:
        time.sleep(1);s=api('/api/state')
    report=dict(session_id=session,arena='orchard',mission='fleet_care',status=s['status'],checks=s['checks'],feedback=s['feedback'],assignments=s['assignments'],results=s['results'],inference=s['inference'],config=s['config'],provider_routes=s['provider_routes'],workers={k:dict(session_id=w['id'],phase=w['phase'],status=w['status'],checks=w['checks'],feedback=w['feedback'],provider_routes=w['provider_routes']) for k,w in s['care_workers'].items()},wall_seconds=s['runtime_state']['active_wall'])
    output=pathlib.Path('docs/evaluations');output.mkdir(exist_ok=True,parents=True)
    (output/f'fleet-care-{session}.json').write_text(json.dumps(report,indent=2))
    exports=pathlib.Path('.runtime/exports');exports.mkdir(exist_ok=True,parents=True)
    for sid in [session,*s['worker_sessions']]:
        try:(exports/f'{sid}.json').write_text(json.dumps(api(f'/api/sessions/{sid}/export')))
        except Exception:print(json.dumps(dict(export_failed=sid)),flush=True)
    print(json.dumps(dict(result=report['status'],checks=report['checks'],report=str(output/f'fleet-care-{session}.json'))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--start',action='store_true');p.add_argument('--seed',type=int,default=7);a=p.parse_args()
    if a.start:
        s=api('/api/reset',dict(mission='full_care',tree_count=10,seed=a.seed,engine='crusoe'));api('/api/start',{})
    else:s=api('/api/state')
    if s.get('mission_type')!='fleet_care':raise SystemExit('Main orchard is not a fleet-care mission')
    monitor(s['id'])
