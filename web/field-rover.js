import * as THREE from 'three';
import {batchStatic} from './batch-geometry.js';
import {box,cylinder,material} from './static-geometry.js';

// Presentation bodywork only. FleetScene keeps this on layer 1 during orchard
// care, outside decision RGB/depth. The calibrated tools live in OrchardArm.
export function fieldRover(id) {
  const g=new THREE.Group();
  const paint=material(id==='R1'?0xb96d39:0xd6a13a,.72);
  const edge=material(0x94713e), dark=material(0x303630), rubber=material(0x242722);
  const tread=material(0x45473d), steel=material(0x9b9b86,.48), ivory=material(0xd5cfb8,.65);
  const glass=material(0x18353e,.17), rim=material(0x101c20,.35);
  const glint=material(0x8cbdc5,.2);

  // A compact, square service chest with a recessed front panel and worn edges.
  box(g,[1.08,.76,1.05],[0,.78,.12],paint);
  box(g,[1.12,.09,1.1],[0,1.16,.12],edge);
  box(g,[1.12,.1,1.1],[0,.42,.12],dark);
  box(g,[.88,.52,.035],[0,.78,-.422],edge);
  box(g,[.8,.44,.025],[0,.79,-.446],paint);
  box(g,[.68,.045,.035],[0,1.035,-.466],dark);
  for(const x of [-.46,.46]) {
    box(g,[.055,.66,.045],[x,.79,-.437],ivory);
    for(const y of [.5,1.08])cylinder(g,[x,y,-.46],[x,y,-.48],.018,.018,steel,8);
  }
  for(let i=0;i<4;i++)box(g,[.23,.022,.018],[-.23,.73+i*.055,-.466],dark);
  // Small rear reservoir and side service plates retain the agricultural identity.
  cylinder(g,[-.37,.78,.69],[.37,.78,.69],.15,.15,ivory,16);
  for(const side of [-1,1]) {
    box(g,[.045,.27,.57],[side*.563,.84,.14],dark);
    box(g,[.065,.19,.4],[side*.59,.87,.12],paint);
    cylinder(g,[side*.56,1.05,.05],[side*.64,1.05,.05],.085,.085,steel,12);
    tracks(g,side,{rubber,tread,steel,dark});
  }

  // Exposed neck, cross-axis hinge and two broad, gently tilted camera housings.
  cylinder(g,[0,1.2,.16],[0,1.43,.04],.065,.055,dark,12);
  cylinder(g,[-.16,1.4,.04],[.16,1.4,.04],.08,.08,steel,12);
  box(g,[.5,.075,.12],[0,1.48,.035],dark);
  for(const side of [-1,1]) {
    const eye=new THREE.Group();eye.position.set(side*.265,1.53,.025);eye.rotation.z=side*-.1;g.add(eye);
    const outline=new THREE.Shape();
    outline.moveTo(-.23,-.11);outline.lineTo(-.18,-.18);outline.lineTo(.15,-.18);
    outline.lineTo(.24,-.08);outline.lineTo(.22,.12);outline.lineTo(.14,.19);
    outline.lineTo(-.16,.19);outline.lineTo(-.24,.1);outline.closePath();
    const housing=new THREE.Mesh(new THREE.ExtrudeGeometry(outline,{depth:.18,bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:.025,bevelThickness:.02}),ivory);
    housing.position.z=-.16;eye.add(housing);
    cylinder(eye,[0,0,-.17],[0,0,-.205],.157,.157,steel,24);
    cylinder(eye,[0,0,-.206],[0,0,-.23],.13,.13,rim,24);
    cylinder(eye,[0,0,-.231],[0,0,-.239],.098,.098,glass,24);
    cylinder(eye,[0,0,-.24],[0,0,-.247],.06,.06,rim,20);
    cylinder(eye,[-.034,.04,-.248],[-.034,.04,-.25],.024,.024,glint,12);
    for(const x of [-.18,.18])cylinder(eye,[x,.105,-.185],[x,.105,-.19],.012,.012,dark,8);
  }
  // The unit identifier stays readable on every worker and the recovery rover.
  const canvas=document.createElement('canvas');canvas.width=256;canvas.height=128;
  const ctx=canvas.getContext('2d');ctx.fillStyle='#d6c89d';ctx.fillRect(0,0,256,128);
  ctx.fillStyle='#303630';ctx.font='bold 62px monospace';ctx.textAlign='center';ctx.fillText(id,128,76);
  ctx.font='bold 20px monospace';ctx.fillText(id==='R1'?'RECOVERY':'WALL-NE',128,108);
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  box(g,[.32,.16,.012],[.2,.82,-.469],new THREE.MeshStandardMaterial({map:texture,roughness:.85}));
  batchStatic(g);
  return g;
}

function tracks(g,side,{rubber,tread,steel,dark}) {
  // Continuous chamfered tracks, with raised shoes and three exposed road wheels.
  const profile=[[-.83,.25],[-.62,.08],[.59,.08],[.83,.27],[.72,.58],[-.64,.58]];
  const shape=new THREE.Shape();profile.forEach(([z,y],i)=>i?shape.lineTo(z,y):shape.moveTo(z,y));shape.closePath();
  const belt=new THREE.Mesh(new THREE.ExtrudeGeometry(shape,{depth:.25,bevelEnabled:true,bevelSegments:1,steps:1,bevelSize:.025,bevelThickness:.015}),rubber);
  belt.rotation.y=Math.PI/2;belt.position.x=side*.69-.125;g.add(belt);
  for(let i=0;i<profile.length;i++) {
    const [z,y]=profile[i], [nz,ny]=profile[(i+1)%profile.length];
    const count=Math.ceil(Math.hypot(nz-z,ny-y)/.12);
    for(let j=0;j<count;j++) {
      const t=(j+.5)/count;
      const shoe=box(g,[.29,.045,.065],[side*.69,y+(ny-y)*t,-(z+(nz-z)*t)],tread);
      shoe.rotation.x=Math.atan2(ny-y,nz-z);
    }
  }
  for(const z of [-.5,0,.5]) {
    cylinder(g,[side*.79,.33,z],[side*.836,.33,z],.19,.19,dark,16);
    cylinder(g,[side*.837,.33,z],[side*.85,.33,z],.115,.115,steel,16);
    cylinder(g,[side*.851,.33,z],[side*.856,.33,z],.045,.045,dark,12);
  }
}
