import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {fieldRover} from '../web/field-rover.js';
import {sampleDepth,calibratedCamera} from '../web/treatment-scene.js';

test('cosmetic fleet bodies remain outside autonomous RGB and depth after scene updates',async()=>{
  const previous=globalThis.document;
  globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})}),createElementNS:()=>({addEventListener(){},removeEventListener(){}})};
  try {
    const {FleetScene}=await import('../web/scene.js');
    const robots=Object.fromEntries(['W1','W2','W3','W4','W5','R1'].map(id=>[id,fieldRover(id)]));
    const view={robots,feedCameras:Object.fromEntries(Object.keys(robots).map(id=>[id,new THREE.PerspectiveCamera()])),armControl:{update(){}}};
    const scene=new THREE.Scene();Object.values(robots).forEach(robot=>scene.add(robot));
    const state={arena:'orchard',vehicles:Object.fromEntries(Object.keys(robots).map((id,i)=>[id,{position:[i*3,0],lifecycle:id==='W5'?'spare':'active'}]))};
    const before=structuredClone(state);
    FleetScene.prototype.update.call(view,state);
    assert.deepEqual(state,before,'rendering must not mutate mission state');
    const config={fov:65,position:[0,1,-3],direction:[0,0,1],up:[0,1,0]};
    const decisionCamera=calibratedCamera(config);
    for(const [id,robot] of Object.entries(robots)) {
      assert.deepEqual(robot.position.toArray(),[state.vehicles[id].position[0],0,0]);
      robot.traverse(mesh=>{if(mesh.isMesh)assert.equal(mesh.layers.test(decisionCamera.layers),false);});
    }
    assert.equal(robots.W5.visible,false);
    const rays=Array.from({length:121},(_,i)=>[(i%11)/10,Math.floor(i/11)/10]);
    assert.ok(sampleDepth(scene,{camera:config,rays}).every(hit=>hit===null));
    // The same geometry is still available to ordinary fleet spectator cameras.
    FleetScene.prototype.update.call(view,{...state,arena:'fleet'});
    assert.ok(sampleDepth(scene,{camera:config,rays}).some(hit=>hit!==null));
  } finally {globalThis.document=previous;}
});
