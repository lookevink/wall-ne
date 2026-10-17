"""Authoritative fleet physics. Policy observations deliberately omit hidden truth."""
import copy
import random
from .common import RecordedWorld, digest, distance, finite, uid, VERSION

TERMINAL = {'completed', 'failed', 'aborted', 'blocked'}
CONTRACT = dict(critical=30, target=65, reserve=20, work_deadline=1200, recovery_deadline=1560, coverage='all')

class Mission(RecordedWorld):
    kind = 'fleet'

    def __init__(self, seed=7, rows=12, contract=None):
        self.id, self.seed, self.version = uid(), seed, VERSION
        self.contract = dict(CONTRACT, **(contract or {}))
        self.contract_hash = digest(self.contract)
        self.time = 0.0
        self.revision = self.seq = 0
        self.status = 'paused'
        self.events, self.receipts, self.assignments = [], {}, {}
        self.prompt_versions = {'planner':'fleet-planner-v1','orchestrator':'fleet-orchestrator-v1','worker':'fleet-worker-v1','retriever':'fleet-retriever-v1','verifier':'fleet-verifier-v1'}
        self.zones, self.vehicles = {}, {}
        rng = random.Random(seed)
        for row in range(rows):
            for segment in range(3):
                key = f'{row}:{segment}'
                moisture = rng.randint(12, 58)
                self.zones[key] = dict(id=key, row=row, segment=segment, position=[(row-5.5)*3.5,-9+segment*8], initial=moisture, moisture=float(moisture), observed=None, inspected_at=None, delivered=0.0, delivered_on_time=0.0)
        self.inventory_hash = digest({k:(v['position'],v['initial']) for k,v in self.zones.items()})
        for i, key in enumerate(['W1','W2','W3','W4','W5','R1']):
            home = [-7.5+3*i,21]
            self.vehicles[key] = dict(id=key, role='retriever' if key=='R1' else 'worker', position=home[:], home=home, battery=100.0, minimum_battery=100.0, water=70.0, lifecycle='spare' if key=='W5' else 'idle', action=None, recovered=False, fault=None)
        self.event('created', seed=seed, contract_hash=self.contract_hash)

    def route(self, start, target):
        if abs(start[0]-target[0]) < 1e-6:
            return [target[:]]
        return [[start[0],16],[target[0],16],target[:]]

    def path_length(self, start, route):
        length = 0
        for target in route:
            length += distance(start,target)
            start = target
        return length

    def estimate(self, vehicle, action, zone=None, target=None):
        v = self.vehicles[vehicle]
        point = self.zones[zone]['position'] if zone else v['home']
        work = 0
        if action == 'inspect': work = 3
        if action == 'water': work = max(0,self.contract['target']-self.zones[zone]['moisture'])/2
        if action == 'retrieve':
            t = self.vehicles[target]
            outward = self.path_length(v['position'],self.route(v['position'],t['position']))
            tow = self.path_length(t['position'],self.route(t['position'],t['home']))
            home = self.path_length(t['home'],self.route(t['home'],v['home']))
            return dict(energy=outward*.13+tow*.24+home*.13+4*.08, duration=outward/1.8+tow/1.3+home/1.8+4, water=0)
        outward = self.path_length(v['position'],self.route(v['position'],point))
        home = 0 if action=='return' else self.path_length(point,self.route(point,v['home']))
        return dict(energy=(outward+home)*.13+work*.08, duration=(outward+home)/1.8+work, water=work*2 if action=='water' else 0)

    def command(self, command_id, robot, action, **args):
        if not isinstance(command_id,str) or not command_id or len(command_id)>120:
            raise ValueError('valid command_id required')
        if command_id in self.receipts:
            return copy.deepcopy(self.receipts[command_id])
        receipt = dict(command_id=command_id, robot_id=robot, action=action, arguments=copy.deepcopy(args), accepted=False, revision=self.revision)
        try:
            if self.status in TERMINAL: raise ValueError('mission is terminal')
            if action == 'assign':
                if robot != 'orchestrator': raise ValueError('orchestrator only')
                row, worker = args['row'], args['vehicle']
                if isinstance(row,bool) or row not in {z['row'] for z in self.zones.values()}: raise ValueError('unknown row')
                v = self.vehicles[worker]
                if v['role']!='worker' or v['lifecycle'] in ('disabled','spare'): raise ValueError('worker unavailable')
                old = self.assignments.get(str(row),{})
                if old and old['vehicle']!=worker and self.vehicles[old['vehicle']]['lifecycle']!='disabled': raise ValueError('row already owned')
                self.assignments[str(row)] = dict(vehicle=worker,version=old.get('version',0)+1)
            elif action == 'activate_spare':
                if robot!='orchestrator' or self.vehicles['W5']['lifecycle']!='spare': raise ValueError('spare unavailable')
                self.vehicles['W5']['lifecycle']='idle'
            elif action == 'claim_complete':
                checks = self.verify()
                if not all(checks.values()): raise ValueError('independent verifier rejects completion claim')
                self.status='completed'
            else:
                v = self.vehicles[robot]
                if v['lifecycle'] in ('disabled','spare') or v['action']: raise ValueError('vehicle unavailable')
                if action not in ('inspect','water','return','service','retrieve'): raise ValueError('unknown action')
                zone = args.get('zone')
                if action in ('inspect','water'):
                    if v['role']!='worker': raise ValueError('worker only')
                    z = self.zones[zone]
                    assignment = self.assignments.get(str(z['row']))
                    if not assignment or assignment['vehicle']!=robot or assignment['version']!=args.get('ownership_version'): raise ValueError('stale or unowned task')
                    if self.time>=self.contract['work_deadline']: raise ValueError('work deadline')
                    if action=='water' and (z['observed'] is None or z['initial']>self.contract['critical']): raise ValueError('inspect and establish eligibility first')
                if action=='service' and distance(v['position'],v['home'])>1e-6: raise ValueError('service only at home')
                if action=='retrieve':
                    t = self.vehicles[args['target']]
                    if v['role']!='retriever' or t['lifecycle']!='disabled' or t['recovered']: raise ValueError('invalid retrieval')
                if action!='service':
                    estimate=self.estimate(robot,action,zone if action in ('inspect','water') else None,args.get('target'))
                    if v['battery']-estimate['energy']<=self.contract['reserve']+3: raise ValueError('safe return reserve guard')
                    if estimate['water']>v['water']+1e-6: raise ValueError('insufficient water; service required')
                point = self.zones[zone]['position'] if action in ('inspect','water') else self.vehicles[args['target']]['position'] if action=='retrieve' else v['home']
                v['action']=dict(id=command_id,kind=action,zone=zone,target=args.get('target'),route=self.route(v['position'],point),stage='travel',remaining=12 if action=='service' else 4 if action=='retrieve' else 3 if action=='inspect' else max(0,self.contract['target']-self.zones[zone]['moisture'])/2 if action=='water' else 0)
                v['lifecycle']='working'
            receipt['accepted']=True
            self.revision+=1
        except (ValueError,KeyError,TypeError) as exc:
            receipt['reason']=str(exc) if isinstance(exc,ValueError) else 'invalid command arguments'
        self.receipts[command_id]=receipt
        self.event('accepted' if receipt['accepted'] else 'rejected',robot,receipt=receipt)
        return copy.deepcopy(receipt)

    def breakdown(self, robot):
        v=self.vehicles[robot]
        if robot=='R1' or v['lifecycle'] in ('disabled','spare'): return
        if v['action']:
            self.event('cancelled',robot,command_id=v['action']['id'],reason='breakdown')
        v.update(action=None,lifecycle='disabled',fault='drive failure',recovered=distance(v['position'],v['home'])<1e-6)
        self.revision+=1
        self.event('breakdown',robot)

    def _finish(self,v):
        a=v['action']
        self.event('completed',v['id'],command_id=a['id'],action=a['kind'])
        v.update(action=None,lifecycle='idle')

    def tick(self, dt):
        finite(dt,0,60)
        while dt>1e-9 and self.status=='running':
            step=min(dt,.25); dt-=step
            self.time+=step; self.revision+=1
            for v in self.vehicles.values():
                a=v['action']
                if not a: continue
                if a['kind'] in ('inspect','water') and self.time>self.contract['work_deadline']:
                    self.event('cancelled',v['id'],command_id=a['id'],reason='work deadline'); v.update(action=None,lifecycle='idle'); continue
                if a['route']:
                    dest=a['route'][0]; length=distance(v['position'],dest)
                    travel=min(length,step*(1.3 if a['stage']=='tow' else 1.8))
                    energy=travel*(.24 if a['stage']=='tow' else .13)
                    if v['battery']-energy<=self.contract['reserve']:
                        self.breakdown(v['id']); self.status='failed'; continue
                    if length>1e-9:
                        v['position']=[p+(q-p)*travel/length for p,q in zip(v['position'],dest)]
                    v['battery']-=energy
                    if a['stage']=='tow': self.vehicles[a['target']]['position']=v['position'][:]
                    if travel>=length-1e-8: a['route'].pop(0)
                elif a['stage']=='tow':
                    self.vehicles[a['target']]['recovered']=True
                    self.event('recovered',a['target'],by=v['id'])
                    self._finish(v)
                else:
                    work=min(step,a['remaining'])
                    if a['kind']=='service':
                        v['battery']=min(100,v['battery']+8*work); v['water']=min(70,v['water']+7*work)
                    else:
                        if v['battery']-.08*work<=self.contract['reserve']:
                            self.status='failed'; continue
                        v['battery']-=.08*work
                    a['remaining']-=work
                    if a['kind']=='water':
                        z=self.zones[a['zone']]; amount=min(work*2,v['water'],self.contract['target']-z['moisture'])
                        v['water']-=amount; z['moisture']+=amount; z['delivered']+=amount
                        if self.time<=self.contract['work_deadline']: z['delivered_on_time']+=amount
                        z['observed']=z['moisture']
                    if a['remaining']<=1e-8:
                        if a['kind']=='inspect':
                            z=self.zones[a['zone']]; z['observed']=z['moisture']; z['inspected_at']=self.time
                            self.event('inspection',v['id'],zone=z['id'],moisture=z['moisture'])
                        if a['kind']=='retrieve':
                            a['stage']='tow'; a['route']=self.route(v['position'],self.vehicles[a['target']]['home'])
                        else: self._finish(v)
                v['minimum_battery']=min(v['minimum_battery'],v['battery'])
            if self.time>=self.contract['recovery_deadline']:
                self.status='completed' if all(self.verify().values()) else 'failed'
                self.event('verification',checks=self.verify())

    def verify(self):
        c=self.contract
        return dict(coverage=all(z['inspected_at'] is not None and z['inspected_at']<=c['work_deadline'] for z in self.zones.values()),
                    critical_water=all(z['delivered_on_time']+1e-6>=c['target']-z['initial'] for z in self.zones.values() if z['initial']<=c['critical']),
                    battery=all(v['minimum_battery']>c['reserve'] for v in self.vehicles.values()),
                    returned=self.time<=c['recovery_deadline'] and all(distance(v['position'],v['home'])<1e-6 and (v['lifecycle']!='disabled' or v['recovered']) for v in self.vehicles.values()),
                    idle=not any(v['action'] for v in self.vehicles.values()),
                    contract=digest(c)==self.contract_hash and digest({k:(v['position'],v['initial']) for k,v in self.zones.items()})==self.inventory_hash)

    def observations(self):
        return dict(mission_id=self.id,kind=self.kind,time=self.time,status=self.status,contract=self.contract.copy(),
                    zones=[dict({k:z[k] for k in ('id','row','position','observed','inspected_at')}, required_remaining=max(0,self.contract['target']-z['observed']) if z['observed'] is not None and z['initial']<=self.contract['critical'] else 0) for z in self.zones.values()],
                    vehicles=copy.deepcopy(self.vehicles),assignments=copy.deepcopy(self.assignments),history=self.events[-12:])

    def snapshot(self):
        state=super().snapshot(); state.update(kind=self.kind,checks=self.verify())
        return state
