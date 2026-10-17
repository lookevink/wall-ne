"""One finite baseline/candidate campaign; every child is an ordinary persisted session."""
import threading
import time
import json
from pathlib import Path
from .common import uid,canonical,digest,implementation_hash,treatment_implementation_hash
from .review import evaluate_pairs

class Campaigns:
    def __init__(self,app): self.app=app; self.active=None; self.lock=threading.Lock()

    def finalize(self,campaign):
        # A local retry envelope bridges a database outage; the database remains authoritative.
        directory=Path(__file__).resolve().parent.parent/'.runtime/campaign-finalization'
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/(campaign['id']+'.json')
        path.write_text(canonical(campaign))
        repo=self.app.repository
        result={k:campaign[k] for k in ('id','baseline_id','candidate_id','manifest','results','reason','passed')}
        existing=repo.read('evaluations',f'id=eq.{campaign["id"]}&limit=1')
        if existing:
            if digest({k:existing[0][k] for k in result})!=digest(result): raise ValueError('evaluation retry conflicts with saved evidence')
        else: repo.request('POST','/rest/v1/evaluations',result)
        repo.request('PATCH',f'/rest/v1/evaluation_campaigns?id=eq.{campaign["id"]}',dict(status='completed',reason=campaign['reason'],results=campaign['results']))
        campaign['status']='completed';path.unlink()
        return campaign

    def retry(self,campaign_id):
        import uuid
        ident=str(uuid.UUID(campaign_id))
        path=Path(__file__).resolve().parent.parent/'.runtime/campaign-finalization'/(ident+'.json')
        if not path.exists(): raise ValueError('no pending campaign finalization')
        return self.finalize(json.loads(path.read_text()))

    def start(self,candidate_id,engine='gemini',trial='wrist'):
        repo=self.app.repository
        with self.lock:
            if self.active and self.active['status']=='running': raise ValueError('a campaign is already running')
            rows=repo.read('prompt_versions',f'id=eq.{candidate_id}&limit=1')
            if not rows or not rows[0]['parent_id'] or not rows[0]['source_review']: raise ValueError('review-linked candidate required')
            candidate=rows[0]
            existing=repo.read('evaluation_campaigns',f'candidate_id=eq.{candidate_id}&limit=1')
            if existing: raise ValueError('one bounded campaign per candidate')
            review=repo.read('reviews',f'id=eq.{candidate["source_review"]}&limit=1')[0]
            source=repo.read('sessions',f'id=eq.{review["session_id"]}&limit=1')[0]
            if source['kind']!='arm': raise ValueError('initial campaign supports articulated missions only')
            source_config=source['metadata']['configuration']
            if source_config.get('engine')!=engine: raise ValueError('campaign must preserve reviewed provider/model condition')
            source_state=repo.restore(source['id'])
            if source_state['trial']!=trial: raise ValueError('campaign must preserve reviewed sensor condition')
            seeds=[source['seed']]+[s for s in (11,23,8,31) if s!=source['seed']][:3]
            cases=[f'seed{s}' for s in seeds]
            manifest=dict(scenarios=cases,seeds=seeds,source_session=source['id'],withheld_case=cases[-1],engine=engine,trial=trial,kind='arm',wall_cap=240,cost_cap=1,command_cap=50,physical_rules='wall-ne/1',models=source_config.get('models'),provider_base=source_config.get('provider_base'),source_code_hash=source_config.get('code_hash'),code_hash=implementation_hash(),checks=7,withheld_condition='protected clover preservation')
            manifest['treatment_code_hash']=treatment_implementation_hash()
            campaign=dict(id=uid(),baseline_id=candidate['parent_id'],candidate_id=candidate_id,manifest=manifest,status='running',results=[],reason='Campaign in progress')
            # Persist the frozen manifest before either prompt runs, separately from final immutable evaluations.
            repo.request('POST','/rest/v1/evaluation_campaigns',campaign)
            self.active=campaign
            threading.Thread(target=self.run,args=(self.active,),daemon=True).start()
            return self.active.copy()

    def run(self,campaign):
        app=self.app;repo=app.repository;manifest=campaign['manifest'];current=None
        try:
            for scenario,seed in zip(manifest['scenarios'],manifest['seeds']):
                for variant,version in [('baseline',campaign['baseline_id']),('candidate',campaign['candidate_id'])]:
                    s=app.reset(True,dict(kind='arm',seed=seed,mode='vision',engine=manifest['engine'],trial=manifest['trial'],prompt_version=version,campaign_id=campaign['id'],model_pins=manifest['models'],provider_base=manifest['provider_base']))
                    current=app.treatment
                    result=dict(scenario=scenario,variant=variant,session_id=s['id'],passed=False,commands=0,cost=None,hard_violations=0,regressions_passed=False,status='created')
                    campaign['results'].append(result)
                    if current.config.get('treatment_code_hash',current.config.get('code_hash'))!=manifest.get('treatment_code_hash',manifest['code_hash']):
                        current.pause('blocked')
                        result.update(status='blocked',reason='Implementation changed since frozen campaign manifest')
                        raise ValueError('implementation changed since frozen campaign manifest')
                    current.start();start=time.monotonic()
                    while current.world.status=='running' and not current.storage_error:
                        if app.treatment is not current: raise ValueError('campaign interrupted by session replacement')
                        if time.monotonic()-start>=240:current.pause('blocked');break
                        time.sleep(.5)
                    accounting_deadline=time.monotonic()+60
                    while current.futures and not current.storage_error and time.monotonic()<accounting_deadline: time.sleep(.5)
                    state=current.snapshot();passed=all(state['checks'].values()) and state['status']=='completed'
                    result.update(passed=passed,commands=state['decisions'],cost=state['inference']['cost'],hard_violations=int(not state['checks']['preserved'] or not state['checks']['battery'] or not state['checks']['inventory']),regressions_passed=state['checks']['preserved'] and state['checks']['inventory'] and (scenario!=manifest['scenarios'][0] or passed),status=state['status'])
                    repo.request('PATCH',f'/rest/v1/evaluation_campaigns?id=eq.{campaign["id"]}',dict(results=campaign['results']))
                    if current.storage_error: raise ValueError('storage failure interrupted campaign')
            passed,reason=evaluate_pairs(manifest,campaign['results'])
        except Exception as exc:
            passed=False;reason='Implementation changed since frozen campaign manifest' if str(exc)=='implementation changed since frozen campaign manifest' else 'Campaign interrupted or external dependency unavailable'
        finally:
            if current and current.world.status=='running' and not current.storage_error: current.pause('aborted')
        campaign.update(status='finalizing',reason=reason,passed=passed)
        try: self.finalize(campaign)
        except Exception: campaign['status']='storage_blocked'
