"""Bounded evidence reviews and a fixed, conservative prompt-promotion rule."""
import difflib
from .common import uid,digest


def permitted_evidence(events,limit=100):
    result=[]
    for e in events[-limit:]:
        if e['type'] in ('slip','contact','extraction','deposit','verification','rejected','inference_error','completed','decision','observation','depth'):
            result.append({k:e[k] for k in ('sequence','type','robot_id','payload') if k in e})
    return result


def evaluate_pairs(manifest,results):
    if len(manifest.get('scenarios',[]))<4 or not manifest.get('withheld_case'):
        return False,'At least four frozen cases including withheld recovery/protection are required'
    baseline={r['scenario']:r for r in results if r['variant']=='baseline'}
    candidate={r['scenario']:r for r in results if r['variant']=='candidate'}
    cases=manifest['scenarios']
    if set(baseline)!=set(cases) or set(candidate)!=set(cases): return False,'Incomplete campaign; baseline remains active'
    if any(c.get('hard_violations',0) or not c.get('regressions_passed',False) for c in candidate.values()): return False,'Candidate violated hard constraints or regressions'
    if any(baseline[k]['passed'] and not candidate[k]['passed'] for k in cases): return False,'Candidate regressed a baseline success'
    b=sum(x['passed'] for x in baseline.values()); c=sum(x['passed'] for x in candidate.values())
    if c>b: return True,'More completely verified missions without regression'
    paired=[k for k in cases if baseline[k]['passed'] and candidate[k]['passed']]
    if not paired: return False,'No paired successful missions'
    if any(baseline[k].get('cost') is None or candidate[k].get('cost') is None for k in paired): return False,'Unknown cost cannot satisfy efficiency tie-break'
    bc=sum(baseline[k]['commands'] for k in paired); cc=sum(candidate[k]['commands'] for k in paired)
    if cc<=bc*.9 and sum(candidate[k]['cost'] for k in paired)<=sum(baseline[k]['cost'] for k in paired): return True,'At least 10% fewer successful-pair commands without greater reported cost'
    return False,'Inconclusive improvement; baseline remains active'


class ReviewService:
    def __init__(self,repository): self.repository=repository

    def create_candidate(self,role,parent_id,text,review_id,evidence_ids):
        if not isinstance(text,str) or not 30<=len(text)<=12000: raise ValueError('bounded prompt text required')
        parent=self.repository.read('prompt_versions',f'id=eq.{parent_id}&limit=1')
        if not parent or parent[0]['role']!=role: raise ValueError('matching immutable parent required')
        review=self.repository.read('reviews',f'id=eq.{review_id}&limit=1')
        if not review or review[0]['candidate_id']: raise ValueError('one candidate per saved review')
        if not evidence_ids: raise ValueError('supporting evidence IDs required')
        candidate=dict(id=uid(),role=role,text=text,hash=digest(text),parent_id=parent_id,source_review=review_id,status='candidate')
        self.repository.request('POST','/rest/v1/prompt_versions',candidate)
        self.repository.request('PATCH',f'/rest/v1/reviews?id=eq.{review_id}',dict(candidate_id=candidate['id']))
        return dict(candidate=candidate,diff='\n'.join(difflib.unified_diff(parent[0]['text'].splitlines(),text.splitlines(),fromfile='baseline',tofile='candidate')))
