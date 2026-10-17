import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import * as THREE from 'three';
import {createTreatmentWorld,updateTreatmentWorld,sampleDepth,calibratedCamera} from '../web/treatment-scene.js';
const result=spawnSync('python3',['-c',`import json
from simulator.manipulation import Manipulation
print(json.dumps(Manipulation(7,'fieldcrew').snapshot()))`],{encoding:'utf8'});
assert.equal(result.status,0,result.stderr);
const state=JSON.parse(result.stdout);
test('FieldCrew tool dimensions and camera layers match the transferred configuration',()=>{
 const world=createTreatmentWorld();updateTreatmentWorld(world,state);
 assert.equal(world.arm.group.visible,false);assert.equal(world.fieldcrewArm.group.visible,true);
 assert.deepEqual(world.fieldcrewArm.fingers[0].geometry.parameters,{width:.018,height:.13,depth:.04,widthSegments:1,heightSegments:1,depthSegments:1});
 assert.equal(world.fieldcrewArm.links[0].geometry.parameters.radiusTop,.045);
 const camera=calibratedCamera(state.camera);
 world.rover.traverse(object=>assert.equal(object.layers.test(camera.layers),false));
 world.fieldcrewArm.group.traverse(object=>assert.equal(object.layers.test(camera.layers),true));
 const initial=sampleDepth(world.scene,{camera:state.camera,rays:[[.5,.5],[.6,.6]]});assert.ok(initial.some(Boolean));
 updateTreatmentWorld(world,{...state,trial:'wrist'});
 assert.equal(world.fieldcrewArm.group.visible,false);assert.equal(world.arm.group.visible,true);
 world.rover.traverse(object=>assert.equal(object.layers.test(camera.layers),true));
});
test('depth skips the same layer-hidden surfaces as RGB',()=>{
 const scene=new THREE.Scene();
 for(const [z,layer] of [[1,1],[0,0]]){const mesh=new THREE.Mesh(new THREE.PlaneGeometry(2,2),new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));mesh.position.z=z;mesh.layers.set(layer);scene.add(mesh);}
 const rows=sampleDepth(scene,{camera:{fov:70,position:[0,0,2],direction:[0,0,-1],up:[0,1,0]},rays:[[.5,.5]]});
 assert.ok(Math.abs(rows[0][4])<1e-9);
});
