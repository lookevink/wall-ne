"""Measure an isolated live full-care run. Requires its orchard browser tab open.

No synthetic sensors or hidden-target controller are used. A passing exit code
requires all ten physical care checks, all five workers and <=180 real seconds.
"""
import argparse
import collections
import json
import pathlib
import time
import urllib.request


def api(base,path,body=None):
    request=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=45) as response:return json.load(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--start',action='store_true')
    parser.add_argument('--controller',choices=['standard','ultra_fast'],default='ultra_fast')
    args=parser.parse_args();base=f'http://127.0.0.1:{args.port}';started=time.monotonic()
    if args.start:
        state=api(base,'/api/reset',dict(mission='full_care',tree_count=10,seed=args.seed,engine='crusoe',speed=16,care_controller=args.controller))
        api(base,'/api/start',{})
    else:state=api(base,'/api/state')
    session=state['id'];last=-10;uninterrupted=True
    if state.get('mission_type')!='fleet_care':raise SystemExit('Not a full-care fleet')
    while True:
        state=api(base,'/api/state')
        if state['id']!=session:raise SystemExit('Run replaced externally')
        if state['status']=='paused':uninterrupted=False
        elapsed=time.monotonic()-started
        if elapsed-last>=10:
            print(json.dumps(dict(wall_seconds=round(elapsed,1),status=state['status'],calls=state['inference']['calls'],completed=sum(a['status']=='completed' for a in state['assignments'].values()),workers={k:dict(stage=w['phase'],status=w['status'],waiting=w['waiting']) for k,w in state['care_workers'].items()})),flush=True);last=elapsed
        if state['status'] in ('completed','failed','blocked','aborted','storage_blocked'):break
        time.sleep(1)
    finished=time.monotonic()-started
    # Account for late provider responses without extending measured completion.
    deadline=time.monotonic()+15
    while state['inference']['pending_calls'] and time.monotonic()<deadline:
        time.sleep(.5);state=api(base,'/api/state')
    report=dict(session_id=session,controller=args.controller,seed=args.seed,status=state['status'],checks=state['checks'],
        measured_wall_seconds=finished if args.start else None,active_wall_seconds=state['runtime_state']['active_wall'],
        timing_scope='Reset through terminal outcome' if args.start else 'Attached monitor; observational only',
        inference=state['inference'],config=state['config'],assignments=state['assignments'],background_sync=state.get('background_sync'),
        workers={k:dict(id=w['id'],phase=w['phase'],status=w['status'],feedback=w['feedback'],inference=w['inference'],storage_timing=w.get('storage_timing',{})) for k,w in state['care_workers'].items()})
    report['passed']=args.start and uninterrupted and len(state['tasks'])==10 and len(state['assignments'])==10 and state['status']=='completed' and all(state['checks'].values()) and finished<=180 and not state['inference']['pending_calls']
    directory=pathlib.Path('docs/evaluations');directory.mkdir(parents=True,exist_ok=True)
    path=directory/f'ultra-fast-{session}.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],report=str(path),seconds=round(finished,2))),flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
