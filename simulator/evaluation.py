"""One finite baseline/candidate campaign; every child is an ordinary persisted session."""
import threading
import time
from .common import uid
from .review import evaluate_pairs

class Campaigns:
    def __init__(self,app): self.app=app; self.active=None; self.lock=threading.Lock()

    def start(self,candidate_id,engine='gemini',trial='wrist'):
        repo=self.app.repository
        with self.lock:
            if self.active and self.active['status']=='running': raise ValueError('a campaign is already running')
            rows=repo.read('prompt_versions',f'id=eq.{candidate_id}&limit=1')
            if not rows or not rows[0]['parent_id'] or not rows[0]['source_review']: raise ValueError('review-linked candidate required')
            candidate=rows[0]
            existing=repo.read('evaluations',f'candidate_id=eq.{candidate_id}&limit=1')
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
            manifest=dict(scenarios=cases,seeds=seeds,source_session=source['id'],withheld_case=cases[-1],engine=engine,trial=trial,kind='arm',wall_cap=240,cost_cap=1,command_cap=50,physical_rules='wall-ne/1',checks=7,withheld_condition='protected clover preservation')
            self.active=dict(id=uid(),baseline_id=candidate['parent_id'],candidate_id=candidate_id,manifest=manifest,status='running',results=[],reason='Campaign in progress')
            # Persist the frozen manifest before either prompt runs, separately from final immutable evaluations.
            repo.request('POST','/rest/v1/evaluation_campaigns',self.active)
            threading.Thread(target=self.run,args=(self.active,),daemon=True).start()
            return self.active.copy()

    def run(self,campaign):
        app=self.app;repo=app.repository;manifest=campaign['manifest'];current=None
        try:
            for scenario,seed in zip(manifest['scenarios'],manifest['seeds']):
                for variant,version in [('baseline',campaign['baseline_id']),('candidate',campaign['candidate_id'])]:
                    s=app.reset(True,dict(kind='arm',seed=seed,mode='vision',engine=manifest['engine'],trial=manifest['trial'],prompt_version=version,campaign_id=campaign['id']))
                    current=app.treatment;current.start();start=time.monotonic()
                    while current.world.status=='running' and not current.storage_error:
                        if app.treatment is not current: raise ValueError('campaign interrupted by session replacement')
                        if time.monotonic()-start>=240:current.pause('blocked');break
                        time.sleep(.5)
                    state=current.snapshot();passed=all(state['checks'].values()) and state['status']=='completed'
                    result=dict(scenario=scenario,variant=variant,session_id=state['id'],passed=passed,commands=state['decisions'],cost=state['inference']['cost'],hard_violations=int(not state['checks']['preserved'] or not state['checks']['battery'] or not state['checks']['inventory']),regressions_passed=state['checks']['preserved'] and state['checks']['inventory'],status=state['status'])
                    campaign['results'].append(result)
                    repo.request('PATCH',f'/rest/v1/evaluation_campaigns?id=eq.{campaign["id"]}',dict(results=campaign['results']))
                    if current.storage_error: raise ValueError('storage failure interrupted campaign')
            passed,reason=evaluate_pairs(manifest,campaign['results'])
        except Exception as exc:
            passed=False;reason='Campaign interrupted or external dependency unavailable'
        finally:
            if current and current.world.status=='running': current.pause('aborted')
        campaign.update(status='completed',reason=reason)
        result={k:campaign[k] for k in ('id','baseline_id','candidate_id','manifest','results','reason')};result['passed']=passed
        repo.request('POST','/rest/v1/evaluations',result)
        repo.request('PATCH',f'/rest/v1/evaluation_campaigns?id=eq.{campaign["id"]}',dict(status='completed',reason=reason))
