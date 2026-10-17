import * as THREE from 'three';
import {batchStatic} from './batch-geometry.js';
import {rover,box,cylinder,material} from './static-geometry.js';

// Fleet-only bodywork. Treatment geometry remains calibrated independently.
export function fieldRover(id) {
  const g=rover(id), orange=material(0xd47b40), dark=material(0x263b36), silver=material(0xa4aaa0,.45), ivory=material(0xe0d6b7);
  box(g,[1.15,.06,.55],[0,.72,-.5],orange);
  for(const side of [-1,1]) {
    box(g,[.12,.15,1.5],[side*.66,.73,0],ivory);
    cylinder(g,[side*.52,.62,-.98],[side*.52,.62,-.78],.045,.045,silver);
  }
  cylinder(g,[-.56,.62,-.98],[.56,.62,-.98],.045,.045,silver);
  // Stereo vision bar, amber beacon and a protected rear water reservoir.
  box(g,[.75,.18,.18],[0,1.37,.14],dark);
  for(const x of [-.26,.26]) {const lens=cylinder(g,[x,1.37,.04],[x,1.37,-.02],.055,.055,material(0x537b80,.22),12);lens.castShadow=false;}
  cylinder(g,[-.4,1.04,.45],[-.4,1.25,.45],.065,.065,orange,12);
  const tank=cylinder(g,[-.43,.72,.5],[.43,.72,.5],.24,.24,ivory,16);
  tank.receiveShadow=true;
  const canvas=document.createElement('canvas');canvas.width=256;canvas.height=128;const ctx=canvas.getContext('2d');
  ctx.fillStyle='#dcd6bd';ctx.fillRect(0,0,256,128);ctx.fillStyle='#293b32';ctx.font='bold 66px monospace';ctx.textAlign='center';ctx.fillText(id,128,88);
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  box(g,[.46,.24,.015],[0,1.03,.115],new THREE.MeshStandardMaterial({map:texture}));
  batchStatic(g);
  return g;
}
