import test from 'node:test';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createTreatmentWorld,sampleDepth} from '../web/treatment-scene.js';
const setup=spawnSync('python3',['-c',`
import json
from simulator.manipulation import Manipulation
from simulator.arm import ik
from simulator.camera import project_pixel,add,matvec
from simulator.lidar import request
from tests.test_treatment import frame
rows=[]
for seed in [7,11,23,8]:
 for name,dx,y,dz in [('initial',0,0,0),('approach',0,.35,.12),('aligned',0,.15,0),('recovery',.12,.25,.12),('offset',-.12,.15,0)]:
  w=Manipulation(seed);x,_,z=w.weed['position']
  if name!='initial':w.joints=ik([x+dx,y,z+dz,0,0,0],w.base())
  f=frame(w);uv=project_pixel(w.camera(),[x,.15,z]);req=request(f,*uv,.24)
  pose=w.tool_pose();probes=[dict(name='central_stem',position=[x,.15,z])]+[dict(name='finger_'+str(sign),position=add(pose['position'],matvec(pose['rotation'],[sign*w.opening/2,fy,fz]))) for sign in (-1,1) for fy in (-.06,0,.06) for fz in (-.015,0,.015)]
  for probe in probes:probe['uv']=project_pixel(w.camera(),probe['position'])
  rows.append(dict(seed=seed,pose=name,state=w.snapshot(),request=req,target_uv=uv,probes=probes))
print(json.dumps(rows))
`],{encoding:'utf8'});
assert.equal(setup.status,0,setup.stderr);
const fixtures=JSON.parse(setup.stdout);
test('actual sensor geometry remains calibrated across approach and recovery views',()=>{
 const samples=[];
 for(const fixture of fixtures){
  const world=createTreatmentWorld(),s=fixture.state;
  world.rover.position.set(s.robot.position[0],0,s.robot.position[1]);world.garden.update(s);world.arm.update(s);world.basin.visible=false;
  const points=sampleDepth(world.scene,fixture.request);
  assert.equal(points.length,169);assert.ok(points.some(Boolean),`${fixture.seed}/${fixture.pose} has no returns`);
  const probeReturns=sampleDepth(world.scene,{...fixture.request,rays:fixture.probes.map(p=>p.uv)});
  samples.push({...fixture,points,probeReturns});
 }
 // Validate every real Three hit against Python camera rays, and summarize known geometry.
 const verify=spawnSync('python3',['-c',`
import sys,json
from simulator.lidar import validate
from simulator.arm_observation import interpret_scan
from simulator.camera import norm,sub
summary=[]
for row in json.load(sys.stdin):
 r=row['request'];s=row['state'];p=validate(r,r['id'],r['frame_id'],r['revision'],row['points'])
 info=interpret_scan(p,r['camera'],s['observations']['tool_pose'],s['opening'],s['robot']['position'])
 counts={k:info['surface_classes'].count(k) for k in set(info['surface_classes'])}
 target=[s['weed']['position'][0],.15,s['weed']['position'][2]];center=p[84]
 visibility={}
 for probe,hit in zip(row['probes'],row['probeReturns']):
  distance=norm(sub(hit[2:],probe['position'])) if hit else None
  group=visibility.setdefault(probe['name'],dict(visible_samples=0,total_samples=0,first_surface_distances_m=[]))
  group['total_samples']+=1;group['visible_samples']+=int(distance is not None and distance<(.03 if probe['name']=='central_stem' else .004) and all(0<=v<=1 for v in probe['uv']));group['first_surface_distances_m'].append(distance)
 for name,group in visibility.items():group['visible']=group['visible_samples']>=(1 if name=='central_stem' else 3)
 summary.append(dict(seed=row['seed'],pose=row['pose'],counts=counts,visibility=visibility,target_uv=row['target_uv'],center_surface_class=info['surface_classes'][84],center_distance_from_grasp_region_m=norm(sub(center[2:],target)) if center else None,grasp_region_occluded=bool(center and norm(sub(center[2:],r['camera']['position']))<norm(sub(target,r['camera']['position']))-.025)))
print(json.dumps(summary))
`],{input:JSON.stringify(samples),encoding:'utf8',maxBuffer:4*1024*1024});
 assert.equal(verify.status,0,verify.stderr);
 const summary=JSON.parse(verify.stdout);
 if(process.env.WALLNE_VISIBILITY_REPORT)writeFileSync(process.env.WALLNE_VISIBILITY_REPORT,JSON.stringify(summary,null,2)+'\n');
 assert.equal(summary.length,20);
 assert.ok(summary.every(x=>Object.keys(x.visibility).length===3));
 assert.ok(Object.values(summary.find(x=>x.seed===7&&x.pose==='offset').visibility).every(v=>v.visible),'known offset control must expose stem and both finger faces');
 assert.ok(summary.some(x=>!x.visibility.central_stem.visible),'occluded fixtures must be detected rather than called visible');
 assert.ok(summary.some(x=>x.counts.robot_geometry));assert.ok(summary.some(x=>x.counts.ground_plane));
 // This proves mixed returns exist, not that a model can identify a stem.
 assert.ok(summary.every(x=>x.target_uv.every(v=>v>=0&&v<=1)));

});
