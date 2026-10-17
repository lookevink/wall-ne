import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {weedMesh,cloverMesh,disposeSpecimen} from '../web/weed-geometry.js';
import {caterpillarMesh,ladybirdMesh} from '../web/insect-geometry.js';
import {Garden} from '../web/care-garden.js';
const spec={id:'weed7',form:'rosette',position:[0,.08,0],leaves:12,size:1,rotation:.6};
function vertices(group){return group.children.filter(o=>o.isMesh).map(o=>Array.from(o.geometry.attributes.position.array));}
test('plant variants are repeatable, finite surfaces and preserve the graspable stem',()=>{
 for(const form of ['rosette','grass','thistle']){
  const a=weedMesh({...spec,form}),b=weedMesh({...spec,form});assert.deepEqual(vertices(a),vertices(b));
  assert.notDeepEqual(vertices(a),vertices(weedMesh({...spec,form,rotation:.8})));
  a.updateMatrixWorld(true);const hits=new THREE.Raycaster(new THREE.Vector3(0,.15,.3),new THREE.Vector3(0,0,-1)).intersectObject(a,true);
  assert.ok(hits.length>0,`${form}: calibrated grasp height must hit a real stem`);
  for(const mesh of a.children){assert.ok(Array.from(mesh.geometry.attributes.position.array).every(Number.isFinite));if(mesh.material.vertexColors)assert.ok(mesh.geometry.attributes.color,'batching must retain leaf markings');}
  const bounds=new THREE.Box3().setFromObject(a);assert.ok(bounds.min.y>=.07);assert.ok(bounds.max.x<.35&&bounds.min.x>-.35);
 }
});
test('insect bodies remain within existing treatment contact neighborhoods',()=>{
 for(const build of [caterpillarMesh,ladybirdMesh]){
  const g=build({id:'pest0',position:[0,0,0]}),bounds=new THREE.Box3().setFromObject(g);
  assert.ok(bounds.min.x>-.09&&bounds.max.x<.09);assert.ok(bounds.min.y>-.14&&bounds.max.y<.14);assert.ok(bounds.min.z>-.02&&bounds.max.z<.05);
  assert.deepEqual(vertices(g),vertices(build({id:'pest0',position:[0,0,0]})));
 }
});
test('protected groundcover has leaflet markings and stays distinct from target material',()=>{
 const cover=cloverMesh({id:'cover',position:[0,0,0]}),weed=weedMesh(spec);
 assert.ok(cover.children.some(m=>m.geometry.attributes.color));assert.notEqual(cover.children.find(m=>m.material.vertexColors).material,weed.children.find(m=>m.material.vertexColors).material);
});
test('removal and reset release old specimen geometry without losing protected organisms',()=>{
 const garden=new Garden(new THREE.Scene());const state={id:'one',weeds:[{...spec,removed:false}],pests:[{id:'pest',position:[0,.5,.2],removed:false}],protected:[{id:'cover',position:[.8,.08,0]}],beneficial:[{id:'ladybird',position:[0,1,.2]}]};
 garden.update(state);const old=garden.targets.weed7;let disposed=0;old.traverse(o=>{if(o.isMesh)o.geometry.addEventListener('dispose',()=>disposed++);});
 state.weeds[0].removed=true;state.pests[0].removed=true;garden.update(state);assert.equal(old.visible,false);assert.equal(garden.targets.pest.visible,false);assert.equal(garden.group.children.filter(g=>g.visible).length,2);
 garden.update({...state,id:'two'});assert.ok(disposed>0);assert.equal(garden.group.children.length,4);disposeSpecimen(garden.group);
});
