"""Rule-based demo. Uses only the public observation projection."""
from .common import distance, uid

class DemoController:
    label = 'Rule-based demo'

    def decisions(self, obs):
        zones, vehicles, assignments = obs['zones'], obs['vehicles'], obs['assignments']
        critical, target = obs['contract']['critical'],obs['contract']['target']
        unfinished_rows={z['row'] for z in zones if z['observed'] is None or z.get('required_remaining',0)>1e-6}
        if any(v['lifecycle']=='disabled' for v in vehicles.values()) and vehicles['W5']['lifecycle']=='spare':
            return [('orchestrator','activate_spare',{})]
        output=[]
        owned={a['vehicle'] for r,a in assignments.items() if int(r) in unfinished_rows and vehicles[a['vehicle']]['lifecycle']!='disabled'}
        for row in sorted(unfinished_rows):
            owner=assignments.get(str(row))
            if owner and vehicles[owner['vehicle']]['lifecycle']!='disabled': continue
            available=[v for v in vehicles.values() if v['role']=='worker' and v['lifecycle']=='idle' and v['id'] not in owned]
            if available:
                v=min(available,key=lambda v:abs(v['position'][0]-next(z['position'][0] for z in zones if z['row']==row)))
                owned.add(v['id']); output.append(('orchestrator','assign',dict(row=row,vehicle=v['id'])))
        if output: return output
        for key,v in vehicles.items():
            if v['lifecycle']!='idle': continue
            home=distance(v['position'],v['home'])<1e-6
            if v['battery']<55 or v['water']<54 and v['role']=='worker':
                output.append((key,'service' if home else 'return',{})); continue
            if v['role']=='retriever':
                disabled=[w for w in vehicles.values() if w['lifecycle']=='disabled' and not w['recovered']]
                if disabled: output.append((key,'retrieve',dict(target=disabled[0]['id'])))
                elif not home: output.append((key,'return',{}))
                continue
            rows=[int(r) for r,a in assignments.items() if a['vehicle']==key]
            candidates=[z for z in zones if z['row'] in rows and z['observed'] is None]
            water=[z for z in zones if z['row'] in rows and z.get('required_remaining',0)>1e-6]
            candidates=water or candidates
            if candidates and obs['time']<obs['contract']['work_deadline']:
                z=min(candidates,key=lambda z:(z['observed'] if water else distance(v['position'],z['position'])))
                action='water' if water else 'inspect'
                output.append((key,action,dict(zone=z['id'],ownership_version=assignments[str(z['row'])]['version'])))
            elif not home: output.append((key,'return',{}))
        return output

    def step(self, mission):
        for robot,action,args in self.decisions(mission.observations()):
            mission.command(uid(),robot,action,**args)
        if all(mission.verify().values()):
            mission.command(uid(),'orchestrator','claim_complete')
