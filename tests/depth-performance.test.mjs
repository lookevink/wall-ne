import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {sampleDepth,calibratedCamera} from '../web/treatment-scene.js';

test('depth broad phase preserves exact hits while excluding distant forest instances',()=>{
 const scene=new THREE.Scene(),geometry=new THREE.BoxGeometry(.2,1,.2),material=new THREE.MeshBasicMaterial();
 const instances=new THREE.InstancedMesh(geometry,material,1001),matrix=new THREE.Matrix4();
 for(let i=0;i<1000;i++)instances.setMatrixAt(i,matrix.makeTranslation(50+i,0,0));
 instances.setMatrixAt(1000,matrix.makeTranslation(0,0,0));scene.add(instances);
 const request={camera:{position:[0,0,3],direction:[0,0,-1],up:[0,1,0],fov:50,near:.05},rays:[[.5,.5],[.48,.5],[.8,.8]]};
 scene.updateMatrixWorld(true);const camera=calibratedCamera(request.camera),raycaster=new THREE.Raycaster();
 const expected=request.rays.map(([u,v])=>{raycaster.setFromCamera(new THREE.Vector2(u*2-1,1-v*2),camera);raycaster.near=.05;raycaster.far=6;const h=raycaster.intersectObject(instances,false)[0];return h?[u,v,h.point.x,h.point.y,h.point.z]:null;});
 let calls=0;const original=THREE.Mesh.prototype.raycast;
 THREE.Mesh.prototype.raycast=function(...args){calls++;return original.apply(this,args);};
 let actual;try{actual=sampleDepth(scene,request);}finally{THREE.Mesh.prototype.raycast=original;}
 assert.deepEqual(actual,expected);assert.equal(calls,request.rays.length);
 geometry.dispose();material.dispose();
});
