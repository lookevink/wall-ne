import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {writeFileSync} from 'node:fs';
import {createTreatmentWorld,updateTreatmentWorld,sampleDepth} from '../web/treatment-scene.js';
const generated=spawnSync('python3',['-c',`import json
from simulator.manipulation import Manipulation
from simulator.arm import ik
from simulator.camera import project_pixel,add,matvec
rows=[]
for seed in (7,11,23,8):
 for name,dx,y,dz in [('initial',0,0,0),('approach',0,.4,0),('aligned',0,.13,0),('recovery',.12,.25,.12),('offset',-.12,.13,0)]:
  w=Manipulation(seed,'fieldcrew');x,_,z=w.weed['position']
  if name!='initial':w.joints=ik([x+dx,y,z+dz,0,0,0],w.base())
  pose=w.tool_pose()
  probes=[dict(name='central_stem_region',position=[x,.13,z])]+[dict(name='finger_'+str(sign),position=add(pose['position'],matvec(pose['rotation'],[sign*w.opening/2,fy,fz]))) for sign in (-1,1) for fy in (-.05,0,.05) for fz in (-.015,0,.015)]
  for p in probes:p['uv']=project_pixel(w.camera(),p['position'])
  rows.append(dict(seed=seed,pose=name,state=w.snapshot(),probes=probes))
print(json.dumps(rows))`],{encoding:'utf8'});
assert.equal(generated.status,0,generated.stderr);
test('FieldCrew visibility probes include approach, alignment, offset and recovery across four seeds',()=>{
 const rows=[];
 for(const fixture of JSON.parse(generated.stdout)){
  const world=createTreatmentWorld(),s=fixture.state;world.rover.position.set(s.robot.position[0],0,s.robot.position[1]);world.basin.visible=false;updateTreatmentWorld(world,s);
  const hits=sampleDepth(world.scene,{camera:s.camera,rays:fixture.probes.map(p=>p.uv)});
  const probes=fixture.probes.map((p,i)=>({...p,first_surface:hits[i]?.slice(2)||null,visible:p.uv.every(v=>v>=0&&v<=1)&&!!hits[i]&&Math.hypot(...hits[i].slice(2).map((v,j)=>v-p.position[j]))<(i===0?.03:.004)}));
  assert.equal(probes.length,19);assert.ok(hits.some(Boolean));
  rows.push({seed:fixture.seed,pose:fixture.pose,probes,visible_finger_probes:probes.slice(1).filter(p=>p.visible).length,central_region_visible:probes[0].visible});
 }
 writeFileSync('docs/evaluations/fieldcrew-visibility-poses.json',JSON.stringify({condition:'fieldcrew',purpose:'Diagnostic first-surface visibility; target positions used only by probes, never model control',finger_tolerance_m:.004,stem_region_tolerance_m:.03,poses:rows},null,2)+'\n');
 assert.equal(rows.length,20);
});
