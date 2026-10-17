import * as THREE from 'three';
import {box, cylinder, material} from './static-geometry.js';
import {random} from './almond-geometry.js';
import {batchStatic} from './batch-geometry.js';
import {groundcover} from './orchard-grass.js';
import {scenery} from './orchard-scenery.js';
import {AISLE_COUNT,ORCHARD,aisleX,rowX,planting} from './orchard-layout.js';

function soilTexture() {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 512;
  const ctx = canvas.getContext('2d'), rng = random(830);
  ctx.fillStyle = '#a79b78'; ctx.fillRect(0,0,512,512);
  for (let i=0;i<28000;i++) {
    const s=.4+rng()*2.4; ctx.fillStyle = ['#c4b38e','#8e8265','#d3c39e','#a99b77'][i%4];
    ctx.globalAlpha=.2+rng()*.35; ctx.fillRect(rng()*512,rng()*512,s,s);
  }
  const t = new THREE.CanvasTexture(canvas); t.wrapS=t.wrapT=THREE.RepeatWrapping; t.repeat.set(22,22); t.colorSpace=THREE.SRGBColorSpace; t.anisotropy=8; return t;
}
// Broken edges soften the wheel-worn strips.
function ribbon(parent,x,width,length,mat,rng,y=.012) {
  const points=[],indices=[];
  for(let i=0;i<=40;i++) {
    const z=-16+i/40*length,drift=(rng()-.5)*.07;
    points.push(x-width*(.35+rng()*.3)+drift,y,z,x+width*(.35+rng()*.3)+drift,y,z);
    if(i<40){const a=i*2;indices.push(a,a+2,a+1,a+1,a+2,a+3);}
  }
  const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(points,3));geo.setIndex(indices);geo.computeVertexNormals();
  const mesh=new THREE.Mesh(geo,mat);mesh.receiveShadow=true;parent.add(mesh);
}
function rootTexture() {
  const c=document.createElement('canvas');c.width=c.height=128;const ctx=c.getContext('2d');
  const fade=ctx.createRadialGradient(64,64,10,64,64,62);fade.addColorStop(0,'rgba(77,65,39,.5)');fade.addColorStop(.5,'rgba(103,87,51,.24)');fade.addColorStop(1,'rgba(103,87,51,0)');
  ctx.fillStyle=fade;ctx.fillRect(0,0,128,128);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t;
}
function lettering(text, width=512, color='#f2e8c9', background='#34463b') {
  const c=document.createElement('canvas'); c.width=width;c.height=128;const ctx=c.getContext('2d');
  ctx.fillStyle=background;ctx.fillRect(0,0,width,128);ctx.fillStyle=color;ctx.font='600 58px monospace';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,width/2,68);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return new THREE.MeshStandardMaterial({map:t,roughness:.9});
}
export function landscape(scene) {
  const structures=new THREE.Group(),rng=random(194),soil=material(0xf1e5cd);soil.map=soilTexture();soil.bumpMap=soil.map;soil.bumpScale=.045;
  const ground=box(scene,[360,.16,360],[0,-.12,0],soil);ground.castShadow=false;
  const sand=material(0xc1b08b),dark=material(0x394940),metal=material(0x7f8b7b,.55),cream=material(0xdcd0af),wood=material(0x82745a);
  const wear=material(0xc0b18d);wear.map=soil.map;
  for(let aisle=0;aisle<AISLE_COUNT;aisle++) {
    const x=aisleX(aisle);
    for(const side of [-1,1])ribbon(structures,x+side*.61,.32,30,wear,rng,.014);
    cylinder(structures,[x,0,14],[x,.9,14],.035,.035,wood);
    const plaque=box(structures,[.6,.32,.06],[x,.85,14],lettering(String(aisle+1).padStart(2,'0'),128));plaque.rotation.y=.1;
  }
  for(let row=0;row<ORCHARD.rows;row++) {
    const x=rowX(row)+.22;
    cylinder(structures,[x,.045,-16],[x,.045,13.3],.018,.018,dark,5);
  }
  const trees=planting(),roots=new THREE.InstancedMesh(new THREE.PlaneGeometry(1,1),new THREE.MeshBasicMaterial({map:rootTexture(),transparent:true,depthWrite:false}),trees.length),rootDummy=new THREE.Object3D();
  trees.forEach((tree,i)=>{rootDummy.position.set(tree.position[0],.018,tree.position[2]);rootDummy.rotation.set(-Math.PI/2,0,tree.rotation);rootDummy.scale.set(1.5+rng()*.4,1.3+rng()*.5,1);rootDummy.updateMatrix();roots.setMatrixAt(i,rootDummy.matrix);});scene.add(roots);
  box(structures,[65,.02,3.5],[0,.012,16],sand);
  box(structures,[30,.024,7], [0,.015,22],material(0x9f9b80));
  for(let i=0;i<6;i++) {
    const x=-7.5+3*i;
    box(structures,[2,.04,3.1],[x,.045,21],material(0x656b58));
    for(const side of [-1,1])box(structures,[.045,.02,3.1],[x+side*.98,.075,21],cream);
    box(structures,[1.6,.03,.045],[x,.078,22.5],cream);
    box(structures,[.34,.85,.25],[x,.45,23],dark);
    box(structures,[.2,.1,.03],[x,.7,22.86],material(0xbbd68d));
  }
  // A corrugated field shed, solar canopy and water storage make the farm legible.
  box(structures,[7,3.2,5],[-27,1.6,20],material(0x8a8b71));
  for(let x=-30.4;x<-23.5;x+=.24)box(structures,[.045,3.2,.07],[x,1.6,22.54],metal);
  box(structures,[2.4,2.5,.12],[-27,1.25,22.57],dark);
  const roof=box(structures,[7.8,.18,5.8],[-27,3.5,20],metal);roof.rotation.z=.08;
  box(structures,[4.8,.62,.1],[-27,2.9,22.7],lettering('WALL–NE / 01'));
  for(const x of [-10,10])for(const z of [19,24])cylinder(structures,[x,0,z],[x,3.1,z],.065,.065,metal);
  const canopy=box(structures,[22,.15,6],[0,3.2,21.5],dark);canopy.rotation.x=-.06;
  const solar=material(0x314a50,.35);
  for(let x=-9.8;x<10;x+=2.2)for(let z=19.5;z<24;z+=1.4)box(structures,[2.07,.04,1.27],[x,3.34-(z-21.5)*.06,z],solar);
  cylinder(structures,[-22,0,20],[-22,2.5,20],1.05,1.05,cream,24);
  for(const y of [.25,.6,.95,1.3,1.65,2,2.35]) {
    const ring=new THREE.Mesh(new THREE.TorusGeometry(1.055,.025,4,24),metal);ring.rotation.x=Math.PI/2;ring.position.set(-22,y,20);structures.add(ring);
  }
  for(let x=-34;x<=34;x+=3.4)cylinder(structures,[x,0,-19],[x,1.2,-19],.045,.04,wood);
  for(const y of [.45,.9])cylinder(structures,[-34,y,-19],[34,y,-19],.012,.012,metal,4);
  batchStatic(structures); scene.add(structures);
  scenery(scene);
  const meadow=groundcover(scene);
  return {ground,wind:meadow.wind};
}
