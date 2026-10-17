import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import * as THREE from 'three';
import {planting} from '../web/orchard-layout.js';
import {OrchardArm} from '../web/orchard-arm.js';
test('physics tree positions match the rendered orchard planting',()=>{
 const physics=JSON.parse(readFileSync(new URL('../simulator/orchard_trees.json',import.meta.url)));
 assert.deepEqual(physics,planting().map(({row,column,position})=>({row,column,position})));
});
test('wrist arm and weeds are attached to the shared orchard scene in world coordinates',()=>{
 const result=spawnSync('python3',['-c',`import json
from simulator.orchard_manipulation import OrchardManipulation
w=OrchardManipulation();w.status='running';w.begin()
while w.robot['action']:w.tick(.05)
print(json.dumps(w.snapshot()))`],{encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);const state=JSON.parse(result.stdout);
 const view={scene:new THREE.Scene(),feedCameras:{}};const arm=new OrchardArm(view);arm.update(state);
 assert.equal(arm.garden.group.parent,view.scene);assert.equal(arm.arm.group.parent,view.scene);
 assert.equal(arm.garden.targets.weed0.position.z,state.weed.position[2]);
 assert.deepEqual(arm.arm.hand.position.toArray(),state.observations.tool_pose.position);
 assert.deepEqual(view.feedCameras.WRIST.position.toArray(),state.camera.position);
 assert.ok(state.camera.position[2]>12);
 const extracted=structuredClone(state);extracted.extracted=true;extracted.holding=true;extracted.weed.removed=true;
 arm.update(extracted);assert.equal(arm.garden.targets.weed0.position.y,state.observations.tool_pose.position[1]-.08);
 arm.update(state);assert.equal(arm.garden.targets.weed0.position.y,0);assert.equal(arm.garden.targets.weed0.visible,true);
});
test('orchard sensor mode disables shader displacement and camera-dependent fruit culling',async()=>{
 const previous=globalThis.document;
 const ctx=new Proxy({createLinearGradient:()=>({addColorStop(){}})},{get:(o,k)=>o[k]||(()=>{})});
 globalThis.document={createElement:()=>({getContext:()=>ctx}),createElementNS:()=>({addEventListener(){},removeEventListener(){}})};
 try{
  const {orchard}=await import('../web/orchard-trees.js');
  const trees=orchard(new THREE.Scene());trees.sensorMode(true);trees.wind(5,false);
  const shader={uniforms:{},vertexShader:'#include <begin_vertex>'};trees.leaves[0].material.onBeforeCompile(shader);
  assert.equal(shader.uniforms.orchardWind.value,0);
  const far=new THREE.PerspectiveCamera();far.position.set(200,200,200);
  for(const fruit of trees.hulls){fruit.onBeforeRender(null,null,far);assert.equal(fruit.count,fruit.userData.fullCount);assert.ok(fruit.count>0);}
  trees.sensorMode(false);trees.hulls[0].onBeforeRender(null,null,far);assert.equal(trees.hulls[0].count,0);
  trees.wind(5,true);assert.equal(shader.uniforms.orchardWind.value,1);
 }finally{globalThis.document=previous;}
});
