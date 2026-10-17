import * as THREE from 'three';
import {box, cylinder, material} from './static-geometry.js';
import {random} from './almond-geometry.js';
import {batchStatic} from './batch-geometry.js';

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
function lettering(text, width=512, color='#f2e8c9', background='#34463b') {
  const c=document.createElement('canvas'); c.width=width;c.height=128;const ctx=c.getContext('2d');
  ctx.fillStyle=background;ctx.fillRect(0,0,width,128);ctx.fillStyle=color;ctx.font='600 58px monospace';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,width/2,68);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return new THREE.MeshStandardMaterial({map:t,roughness:.9});
}
export function landscape(scene) {
  const structures=new THREE.Group(),rng=random(194),soil=material(0xddd0af);soil.map=soilTexture();soil.bumpMap=soil.map;soil.bumpScale=.045;
  const ground=box(scene,[360,.16,360],[0,-.12,0],soil);ground.castShadow=false;
  const sand=material(0xc1b08b),grass=material(0x7b8050),dark=material(0x394940),metal=material(0x7f8b7b,.55),cream=material(0xdcd0af),wood=material(0x82745a);
  for(let row=0;row<12;row++) {
    const x=(row-5.5)*3.5;
    // Dry wheel tracks, central cover crop, drip tape on either side of each lane.
    box(structures,[.62,.012,27],[x,.006,-.5],grass);
    for(const side of [-1,1]) {
      box(structures,[.36,.014,28],[x+side*.61,.008,-.5],sand);
      cylinder(structures,[x+side*1.05,.06,-14],[x+side*1.05,.06,13],.022,.022,dark,5);
    }
    cylinder(structures,[x,0,14],[x,.9,14],.035,.035,wood);
    const plaque=box(structures,[.6,.32,.06],[x,.85,14],lettering(String(row+1).padStart(2,'0'),128));plaque.rotation.y=.1;
  }
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
  // Rolling, dry hills beyond the cultivated block, never on rover routes.
  for(let i=0;i<11;i++) {
    const geo=new THREE.SphereGeometry(1,20,10),hill=new THREE.Mesh(geo,material(i%2?0xb7ad8b:0xa8a58a));
    hill.position.set(-145+i*29,-4,-95-rng()*35);hill.scale.set(30+rng()*25,8+rng()*12,26+rng()*20);scene.add(hill);
  }
  batchStatic(structures); scene.add(structures);
  const count=7000,blades=new THREE.InstancedMesh(new THREE.PlaneGeometry(.045,.22),new THREE.MeshStandardMaterial({color:0x929761,side:THREE.DoubleSide,roughness:1}),count),dummy=new THREE.Object3D();
  for(let i=0;i<count;i++) {
    const row=i%12, x=(row-5.5)*3.5+(rng()-.5)*.56;
    dummy.position.set(x,.08,-13+rng()*26);dummy.rotation.set((rng()-.5)*.4,rng()*Math.PI,(rng()-.5)*.5);dummy.scale.setScalar(.45+rng()*.85);dummy.updateMatrix();blades.setMatrixAt(i,dummy.matrix);
  }
  scene.add(blades);return ground;
}
