import * as THREE from 'three';
import {cylinder} from './static-geometry.js';
import {random} from './almond-geometry.js';
import {batchStatic} from './batch-geometry.js';

// These are real surfaces, so RGB and depth see the same folded leaves.
const leafMaterial = new THREE.MeshStandardMaterial({color:0x35652d, roughness:.86, side:THREE.DoubleSide, vertexColors:true});
function leafSurface() {
  const w=128,h=256,data=new Uint8Array(w*h*4),rng=random(413);
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const u=x/(w-1),v=y/(h-1),edge=Math.abs(u-.5),vein=Math.abs(((v+edge*.42)*11)%1-.5);
    let value=.82+.045*Math.sin(u*38+v*7)*Math.sin(v*43)+rng()*.055;
    if(edge<.012)value=.98;else if(vein<.025)value+=.07;
    const n=(y*w+x)*4;data[n]=Math.min(255,value*255);data[n+1]=Math.min(255,value*255);data[n+2]=Math.min(255,value*.94*255);data[n+3]=255;
  }
  const t=new THREE.DataTexture(data,w,h);t.colorSpace=THREE.SRGBColorSpace;t.magFilter=THREE.LinearFilter;t.minFilter=THREE.LinearMipmapLinearFilter;t.generateMipmaps=true;t.needsUpdate=true;return t;
}
leafMaterial.map=leafSurface();
const stemMaterial = new THREE.MeshStandardMaterial({color:0x365a2c, roughness:.9});
const veinMaterial = new THREE.MeshStandardMaterial({color:0x567346, roughness:.95});
const dryMaterial = new THREE.MeshStandardMaterial({color:0x857043, roughness:1});
const cloverMaterial = new THREE.MeshStandardMaterial({color:0x8eac65, roughness:.87, side:THREE.DoubleSide, vertexColors:true});
// Keep the established color classes readable under the lab's unusually bright
// lights, while retaining surface shading. This same material is used in every view.
leafMaterial.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <opaque_fragment>', 'outgoingLight = mix(diffuseColor.rgb, outgoingLight, .16);\n#include <opaque_fragment>');};
leafMaterial.customProgramCacheKey=()=> 'specimen-leaf-lighting-v1';
const rootMaterial = new THREE.MeshStandardMaterial({color:0x9b8261, roughness:1});

function seedFor(spec) {
  const text=`${spec.form||'clover'}:${spec.id||''}:${spec.rotation||0}:${spec.size||1}`;
  let seed=2166136261;for(const c of text)seed=Math.imul(seed^c.charCodeAt(0),16777619);return seed>>>0;
}
function blade({length,width,rise,angle,base,form,seed}) {
  const rng=random(seed),steps=form==='grass'?18:32,positions=[],colors=[],uvs=[],indices=[];
  const lean=(rng()-.5)*.055, curl=form==='clover'?.006:.018+rng()*.025;
  const point=(t,side)=>{
    let envelope=Math.pow(Math.sin(Math.PI*t),.8);
    if(form==='rosette')envelope*=.42+.58*Math.pow(.5+.5*Math.sin(t*Math.PI*12),.45);
    if(form==='thistle')envelope*=.35+.65*Math.pow(.5+.5*Math.sin(t*Math.PI*16),2);
    if(form==='clover')envelope=Math.pow(Math.sin(Math.PI*t),.48)*(1-.1*Math.exp(-Math.pow((t-.95)*18,2)));
    const w=width*envelope*side;
    const r=length*t, sideways=w+lean*t*t;
    const y=form==='grass'?base+rise*Math.sin(t*2.05):form==='clover'?base+rise*Math.sin(t*Math.PI):base*(1-t)+rise*Math.sin(t*Math.PI)+.012*t;
    const fold=(1-Math.abs(side))*width*.22*Math.sin(t*Math.PI);
    return [Math.cos(angle)*r-Math.sin(angle)*sideways,y+fold+curl*t*t*side*Math.sin(t*Math.PI),Math.sin(angle)*r+Math.cos(angle)*sideways];
  };
  for(let j=0;j<=steps;j++)for(const side of [-1,-.05,0,.05,1]) {
    const t=j/steps;positions.push(...point(t,side));uvs.push((side+1)/2,t);
    let shade=.72+rng()*.16+(1-Math.abs(side))*.16;
    if(side===0)shade=1.25;
    const stripe=form==='clover'&&Math.abs(t-(.55+Math.abs(side)*.18))<.045;
    if(stripe)colors.push(1.7,1.65,1.4);else colors.push(shade,shade,shade*.94);
  }
  for(let j=0;j<steps;j++)for(let k=0;k<4;k++){const a=j*5+k;indices.push(a,a+5,a+1,a+1,a+5,a+6);}
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));geometry.setIndex(indices);geometry.computeVertexNormals();
  return {geometry,point};
}
function addRoots(g,form,rng) {
  if(form==='grass') {
    for(let i=0;i<18;i++){const a=rng()*6.28,end=[Math.cos(a)*.07,-.09-rng()*.12,Math.sin(a)*.07];cylinder(g,[0,0,0],end,.0025,.0007,rootMaterial,4);}
  } else {
    cylinder(g,[0,0,0],[.012,-.2,.015],.019,.004,rootMaterial,7);
    for(let i=0;i<12;i++){const y=-.025-i*.012,a=rng()*6.28;cylinder(g,[.005,y,.005],[Math.cos(a)*.055,y-.04-rng()*.04,Math.sin(a)*.055],.0028,.0006,rootMaterial,4);}
  }
}
export function weedMesh(spec,{roots=false}={}) {
  const g=new THREE.Group(),rng=random(seedFor(spec)),form=spec.form||'rosette',count=spec.leaves||12,size=spec.size||1;
  const centerY=form==='thistle'?.18:.10;
  cylinder(g,[0,0,0],[0,centerY,0],.018,.012,stemMaterial,8);
  for(let i=0;i<count;i++) {
    const a=i*2.399963+(spec.rotation||0)+(rng()-.5)*.23;
    const length=(form==='grass'?.18:.175)*(.78+rng()*.22);
    const rise=form==='grass'?.22+rng()*.13:.06+rng()*.045;
    const width=form==='grass'?.009+rng()*.006:form==='thistle'?.038:.034;
    const base=form==='grass'?.025+centerY*(i%3)/3:centerY*.7-(i%3)*.014;
    const b=blade({length,width,rise,angle:a,base,form,seed:seedFor(spec)+i*31});
    const leaf=new THREE.Mesh(b.geometry,leafMaterial);leaf.castShadow=leaf.receiveShadow=true;g.add(leaf);
    cylinder(g,[0,centerY*.7,0],b.point(.25,0),.003,.0015,stemMaterial,5);
    if(form!=='grass') {
      for(let j=1;j<=4;j++)for(const side of [-1,1]) {
        const t=.2+j*.13;cylinder(g,b.point(t-.075,0),b.point(t,side*.8),.0008,.0003,veinMaterial,3);
      }
    }
    if(form==='thistle') {
      for(let j=1;j<8;j++)for(const side of [-1,1]) {
        const t=(j+.25)/8,p=b.point(t,side),end=[p[0]+Math.cos(a+side*.9)*.014,p[1]+.006,p[2]+Math.sin(a+side*.9)*.014];
        cylinder(g,p,end,.0012,0,dryMaterial,3);
      }
    }
  }
  // A few tightly furled new leaves break the radial symmetry at the crown.
  for(let i=0;i<3;i++) {
    const b=blade({length:.065,width:.009,rise:.08,angle:i*2.4,base:centerY-.02,form:'grass',seed:i+11});g.add(new THREE.Mesh(b.geometry,leafMaterial));
  }
  if(roots)addRoots(g,form,rng);
  batchStatic(g);g.scale.setScalar(size);g.position.set(...(spec.position||[0,0,0]));g.userData.form=form;return g;
}
export function cloverMesh(spec) {
  const g=new THREE.Group(),rng=random(seedFor(spec));
  for(let i=0;i<7;i++) {
    const a=i*2.39996,x=Math.cos(a)*(.035+rng()*.085),z=Math.sin(a)*(.035+rng()*.085),height=.035+rng()*.06;
    cylinder(g,[x*.35,0,z*.35],[x,height,z],.0018,.0012,veinMaterial,5);
    for(let j=0;j<3;j++) {
      const angle=a+j*Math.PI*2/3,b=blade({length:.065,width:.026,rise:.009,angle,base:height,form:'clover',seed:i*17+j});
      b.geometry.translate(x,0,z);const leaf=new THREE.Mesh(b.geometry,cloverMaterial);leaf.castShadow=leaf.receiveShadow=true;g.add(leaf);
    }
  }
  batchStatic(g);g.position.set(...(spec.position||[0,0,0]));return g;
}
export function disposeSpecimen(group) {
  // Materials are shared across sessions; only instance-owned geometry is released.
  group.traverse(o=>{if(o.isMesh)o.geometry.dispose();for(const mat of o.userData.ownedMaterials||[])mat.dispose();});
}
