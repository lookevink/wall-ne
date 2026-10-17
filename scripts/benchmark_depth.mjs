import * as THREE from 'three';
import {readFileSync,writeFileSync} from 'node:fs';
import {sampleDepth,calibratedCamera} from '../web/treatment-scene.js';
import {OrchardArm} from '../web/orchard-arm.js';
const ctx=new Proxy({createLinearGradient:()=>({addColorStop(){}})},{get:(o,k)=>o[k]||(()=>{})});
globalThis.document={createElement:()=>({getContext:()=>ctx}),createElementNS:()=>({addEventListener(){},removeEventListener(){}})};
const {orchard}=await import('../web/orchard-trees.js');
if(!process.argv[2])throw Error('Usage: node scripts/benchmark_depth.mjs <recorded-api-state.json>');
const state=JSON.parse(readFileSync(process.argv[2],'utf8'));
const scene=new THREE.Scene(),view={scene,feedCameras:{}};view.trees=orchard(scene);
const arm=new OrchardArm(view);arm.update(state);
const request=Object.values(state.care_workers).find(w=>w.depth_request)?.depth_request;
if(!request)throw Error('No recorded scan request');
function original(){const camera=calibratedCamera(request.camera),raycaster=new THREE.Raycaster();scene.updateMatrixWorld(true);const meshes=[];scene.traverseVisible(o=>{if(o.isMesh&&!o.userData.overlay&&o.layers.test(camera.layers))meshes.push(o);});return request.rays.map(([u,v])=>{raycaster.setFromCamera(new THREE.Vector2(u*2-1,1-v*2),camera);raycaster.near=.05;raycaster.far=6;const hit=raycaster.intersectObjects(meshes,false)[0];return hit?[u,v,hit.point.x,hit.point.y,hit.point.z]:null;});}
let t=performance.now();const before=original(),beforeMs=performance.now()-t;t=performance.now();const after=sampleDepth(scene,request),afterMs=performance.now()-t;
const equal=before.every((a,i)=>a===null?after[i]===null:after[i]&&a.every((v,j)=>Math.abs(v-after[i][j])<1e-8));
const result={scope:'CPU depth scan with actual orchard instancing and recorded fleet geometry; no WebGL renderer',rays:request.rays.length,before_ms:beforeMs,after_ms:afterMs,speedup:beforeMs/afterMs,equivalent_within_m:1e-8,equivalent:equal};
writeFileSync('docs/evaluations/ultra-fast-depth.json',JSON.stringify(result,null,2)+'\n');console.log(result);if(!equal)process.exitCode=1;
