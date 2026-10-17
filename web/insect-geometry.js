import * as THREE from 'three';
import {cylinder} from './static-geometry.js';
import {random} from './almond-geometry.js';
import {batchStatic} from './batch-geometry.js';

const skin=new THREE.MeshStandardMaterial({color:0x5b4054,roughness:.82});
skin.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <opaque_fragment>', 'outgoingLight = mix(diffuseColor.rgb, outgoingLight, .1);\n#include <opaque_fragment>');};
skin.customProgramCacheKey=()=> 'specimen-larva-lighting-v1';

const head=new THREE.MeshStandardMaterial({color:0x352a27,roughness:.48});
const stripe=new THREE.MeshStandardMaterial({color:0xb9a28b,roughness:.85});
const legs=new THREE.MeshStandardMaterial({color:0x584637,roughness:.72});
const shell=new THREE.MeshStandardMaterial({color:0xb92916,roughness:.32});
const black=new THREE.MeshStandardMaterial({color:0x141b15,roughness:.45});
const ivory=new THREE.MeshStandardMaterial({color:0xd0c8a6,roughness:.75});
function ellipsoid(g,position,scale,mat,segments=14) {
  const mesh=new THREE.Mesh(new THREE.SphereGeometry(1,segments,10),mat);mesh.position.set(...position);mesh.scale.set(...scale);mesh.castShadow=mesh.receiveShadow=true;g.add(mesh);return mesh;
}
export function caterpillarMesh(spec) {
  const g=new THREE.Group(),rng=random((spec.id||'pest').split('').reduce((n,c)=>n*31+c.charCodeAt(0),17));
  const path=t=>[Math.sin(t*4.8+.4)*.007,(t-.5)*.18,.011+Math.sin(t*Math.PI)*.007];
  // One continuous skin, with shallow intersegment folds rather than stacked balls.
  const vertices=[],colors=[],indices=[],rings=144,sides=20;
  for(let j=0;j<=rings;j++){
    const t=j/rings,p=path(t),phase=(t*12)%1,fold=Math.pow(.5+.5*Math.cos(phase*Math.PI*2),8);
    const radius=(.014+Math.sin(t*Math.PI)*.007)*(1-fold*.12);
    for(let k=0;k<=sides;k++){
      const a=k/sides*Math.PI*2;vertices.push(p[0]+Math.cos(a)*radius,p[1],p[2]+Math.sin(a)*radius*.75);
      const m=.86+rng()*.1,band=fold*.3;colors.push(m+band,m+band*.85,m+band*.7);
      if(j<rings&&k<sides){const n=j*(sides+1)+k;indices.push(n,n+sides+1,n+1,n+1,n+sides+1,n+sides+2);}
    }
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geometry.setIndex(indices);geometry.computeVertexNormals();
  const bodyMaterial=skin.clone();bodyMaterial.vertexColors=true;bodyMaterial.onBeforeCompile=skin.onBeforeCompile;bodyMaterial.customProgramCacheKey=skin.customProgramCacheKey;
  const body=new THREE.Mesh(geometry,bodyMaterial);g.add(body);g.userData.ownedMaterials=[bodyMaterial];
  // Head, three thoracic segments, and an articulated abdomen. The silhouette
  // stays inside the existing vacuum contact footprint; no decorative platform.
  for(let i=0;i<12;i++) {
    const t=i/11,p=path(t),radius=.014+Math.sin(t*Math.PI)*.007;
    for(const side of [-1,1]) {
      // Spiracles on the sides; a fine dorsal stripe and sparse tactile setae.
      ellipsoid(g,[p[0]+side*radius*.76,p[1],p[2]+radius*.39],[.0017,.0012,.0011],head,6);
      if(i>2&&i<10)ellipsoid(g,[p[0]+side*.006,p[1],p[2]+radius*.66],[.0012,.009,.0008],stripe,6);
      if(i%2===0)cylinder(g,[p[0]+side*radius*.7,p[1],p[2]+.01],[p[0]+side*(radius+.005),p[1]+(rng()-.5)*.008,p[2]+.016],.00035,.0001,stripe,3);
      if(i>=8) {
        const knee=[p[0]+side*.019,p[1]-.005,.006],foot=[p[0]+side*.023,p[1]-.011,-.002];
        cylinder(g,[p[0]+side*.012,p[1],p[2]-.004],knee,.0022,.0018,legs,5);cylinder(g,knee,foot,.0018,.0009,legs,5);
      } else if([1,3,4,5,6].includes(i))ellipsoid(g,[p[0]+side*.012,p[1],-.001],[.005,.006,.007],legs,8);
    }
  }
  const top=path(1);ellipsoid(g,[top[0],.106,.012],[.016,.017,.012],head);
  for(const side of [-1,1]) {
    ellipsoid(g,[top[0]+side*.009,.113,.021],[.002,.002,.0015],black,6);
    cylinder(g,[top[0]+side*.008,.12,.012],[top[0]+side*.012,.129,.015],.001,.0004,legs,4);
  }
  batchStatic(g);g.position.set(...spec.position);return g;
}
export function ladybirdMesh(spec) {
  const g=new THREE.Group();
  // Flattened underside sits on bark; two domed elytra meet at the midline.
  ellipsoid(g,[0,0,0],[.031,.039,.012],black);
  for(const side of [-1,1]){
    const verts=[],ids=[],across=16,along=24;
    for(let j=0;j<=along;j++)for(let k=0;k<=across;k++){
      const v=j/along*Math.PI,u=k/across*Math.PI/2;
      verts.push(side*(.0003+.032*Math.sin(u)*Math.sin(v)),Math.cos(v)*.039-.004,.003+.025*Math.cos(u)*Math.sin(v));
      if(j<along&&k<across){const n=j*(across+1)+k;if(side===-1)ids.push(n,n+1,n+across+1,n+1,n+across+2,n+across+1);else ids.push(n,n+across+1,n+1,n+1,n+across+1,n+across+2);}
    }
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));geo.setIndex(ids);geo.computeVertexNormals();g.add(new THREE.Mesh(geo,shell));
  }
  const surface=(x,y)=>.003+.025*Math.sqrt(Math.max(0,1-(x/.032)**2-((y+.004)/.039)**2));
  for(let j=0;j<12;j++){const a=-.039+j*.006,b=a+.006;cylinder(g,[0,a,surface(0,a)],[0,b,surface(0,b)],.00045,.00045,black,4);}
  const spot=(x,y,rx,ry)=>{
    const verts=[x,y,surface(x,y)+.001],ids=[];
    for(let i=0;i<=24;i++){const a=i/24*Math.PI*2,px=x+Math.cos(a)*rx,py=y+Math.sin(a)*ry;verts.push(px,py,surface(px,py)+.001);if(i<24)ids.push(0,i+1,i+2);}
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));geo.setIndex(ids);geo.computeVertexNormals();g.add(new THREE.Mesh(geo,black));
  };
  ellipsoid(g,[0,.030,.006],[.025,.015,.016],black);
  for(const side of [-1,1]) {
    ellipsoid(g,[side*.017,.035,.018],[.0035,.004,.0012],ivory,8);
    for(let i=0;i<3;i++) {
      const y=-.026+i*.02,knee=[side*.038,y+.009,.001],foot=[side*.045,y+.002,-.005];
      cylinder(g,[side*.022,y,.001],knee,.0016,.0012,black,5);cylinder(g,knee,foot,.0012,.0006,black,5);
      const x=side*(i===1?.022:.012),spotY=-.024+i*.019;
      spot(x,spotY,.005,.006);
    }
    cylinder(g,[side*.009,.043,.005],[side*.016,.055,.005],.001,.0006,black,4);
    ellipsoid(g,[side*.016,.056,.005],[.0015,.002,.0012],black,6);
  }
  ellipsoid(g,[0,.044,.003],[.012,.01,.009],black);
  batchStatic(g);g.position.set(...spec.position);return g;
}
