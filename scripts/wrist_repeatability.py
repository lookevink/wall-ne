#!/usr/bin/env python3
"""One predeclared five-run series: same model, camera, prompt, mechanics and caps."""
import json
import pathlib
import uuid
from simulator.common import load_env,treatment_implementation_hash,utc
from simulator.inference import Adapter
from simulator.persistence import Repository
from scripts.arm_experiments import trial,api

def main():
    load_env();adapter=Adapter('nemotron','treatment');repo=Repository()
    prompt=repo.read('prompt_versions','role=eq.treatment&status=eq.active&limit=1')[0]
    expected=dict(model=adapter.model,provider_base=adapter.base,treatment_code_hash=treatment_implementation_hash(),prompt_version=prompt['id'])
    series=dict(id=str(uuid.uuid4()),created_at=utc(),status='running',manifest=dict(engine='nemotron',trial='wrist',seeds=[7,7,11,23,8],wall_cap_seconds=240,reported_cost_cap_dollars=1,command_cap=50,condition=expected,purpose='Post-change repeatability and held-out accuracy; not a causal before/after comparison or prompt promotion'),results=[])
    path=pathlib.Path('docs/evaluations')/('wrist-repeatability-'+series['id']+'.json')
    def save():path.write_text(json.dumps(series,indent=2))
    # Avoid replacing unrelated operator work.
    current=api('/api/treatment/state')
    if current['status']=='running' or current['inference'].get('pending_calls'):raise RuntimeError('current treatment must be inactive with settled accounting')
    save();print(json.dumps(dict(report=str(path),manifest=series['manifest'])),flush=True)
    try:
        for index,seed in enumerate(series['manifest']['seeds']):
            if treatment_implementation_hash()!=expected['treatment_code_hash']:raise RuntimeError('implementation changed during series')
            result=trial('nemotron','wrist',seed,expected);result['index']=index;series['results'].append(result);save();print(json.dumps(result),flush=True)
            if result['pending_calls']:raise RuntimeError('outstanding inference accounting')
        if treatment_implementation_hash()!=expected['treatment_code_hash']:raise RuntimeError('implementation changed during series')
        series['status']='completed'
        series['complete_missions']=sum(r['status']=='completed' and all(r['checks'].values()) for r in series['results'])
        series['repeatable_across_series']=series['complete_missions']==len(series['manifest']['seeds'])
    except Exception as exc:
        series.update(status='interrupted',reason=str(exc))
        raise
    finally:save();print(json.dumps(dict(report=str(path),status=series['status'],complete_missions=series.get('complete_missions'))),flush=True)

if __name__=='__main__':main()
