import * as THREE from 'three';
import {random} from './almond-geometry.js';
import {AISLE_COUNT,aisleX} from './orchard-layout.js';

// Folded, tapering blades grow out of a shared crown. No alpha cards or rectangles.
export function grassClump(seed) {
  const rng=random(seed),positions=[],colors=[],indices=[];
  for(let blade=0;blade<5;blade++) {
    const a=rng()*Math.PI*2,h=.16+rng()*.22,w=.009+rng()*.013,bend=.05+rng()*.19;
    const ox=(rng()-.5)*.11,oz=(rng()-.5)*.11,start=positions.length/3;
    for(let level=0;level<4;level++) {
      const t=level/3,width=w*(1-t)*(.8+Math.sin(t*Math.PI)*.35),lean=bend*t*t;
      const cx=ox+Math.cos(a)*lean,cz=oz+Math.sin(a)*lean;
      for(let side=-1;side<=1;side++) {
        positions.push(cx+Math.cos(a+Math.PI/2)*width*side,h*t,cz+Math.sin(a+Math.PI/2)*width*side+(side===0?.008*Math.sin(t*Math.PI):0));
        const tone=.46+t*.46+(side===0?.09:0);colors.push(tone*.88,tone,tone*.66);
      }
      if(level<3)for(let side=0;side<2;side++) {
        const i=start+level*3+side;indices.push(i,i+3,i+1,i+1,i+3,i+4);
      }
    }
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geometry.setIndex(indices);geometry.computeVertexNormals();return geometry;
}
function meadowFloor(scene) {
  const c=document.createElement('canvas');c.width=1024;c.height=768;const ctx=c.getContext('2d'),rng=random(947);
  const px=x=>(x+70)/140*c.width,pz=z=>(z+65)/90*c.height;
  for(let i=0;i<1700;i++) {
    const back=i%3===0,x=back?-47+rng()*94:(i%2?1:-1)*(24+rng()*25),z=back?-24-rng()*26:-43+rng()*55;
    const radius=1.2+rng()*4.5,fade=ctx.createRadialGradient(px(x),pz(z),0,px(x),pz(z),radius*c.width/140);
    fade.addColorStop(0,i%4===0?'rgba(151,147,97,.46)':'rgba(109,127,73,.4)');fade.addColorStop(1,'rgba(109,127,73,0)');
    ctx.fillStyle=fade;ctx.fillRect(px(x-radius),pz(z-radius),radius*2*c.width/140,radius*2*c.height/90);
  }
  const map=new THREE.CanvasTexture(c);map.colorSpace=THREE.SRGBColorSpace;map.anisotropy=8;
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(140,90),new THREE.MeshStandardMaterial({map,transparent:true,depthWrite:false,roughness:1}));
  floor.rotation.x=-Math.PI/2;floor.position.set(0,-.025,-20);floor.receiveShadow=true;scene.add(floor);
}
export function groundcover(scene) {
  meadowFloor(scene);
  const rng=random(7351),clock={value:0};
  const mat=new THREE.MeshLambertMaterial({color:0xffffff,vertexColors:true,side:THREE.DoubleSide});
  mat.onBeforeCompile=shader=>{
    shader.uniforms.meadowTime=clock;shader.vertexShader='uniform float meadowTime;\n'+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
      #ifdef USE_INSTANCING
      vec3 root=instanceMatrix[3].xyz;
      float wave=sin(meadowTime*1.4+root.x*.35+root.z*.7)+.4*sin(meadowTime*2.3+root.z*1.2);
      transformed.x += wave*position.y*position.y*.5;
      transformed.z += cos(meadowTime+root.x*.45)*position.y*position.y*.25;
      #endif`);
  };mat.customProgramCacheKey=()=> 'meadow-blades-v1';
  const groups=Array.from({length:4},()=>[]);
  function plant(x,z,height,edge=false){
    // Slow variation creates contiguous green and straw patches, not random confetti.
    const patch=(Math.sin(x*.7+z*.24)+Math.sin(z*.65-x*.18))*.25+.5;
    groups[Math.floor(rng()*4)].push({x,z,height,rotation:rng()*Math.PI*2,width:.65+rng()*.8,patch,edge});
  }
  for(let row=0;row<AISLE_COUNT;row++)for(let i=0;i<1150;i++) {
    const z=-15.8+rng()*29.5,edge=.42+.08*Math.sin(z*1.4+row),offset=(rng()-.5)*edge*2;
    plant(aisleX(row)+offset,z,.35+rng()*.28);
    if(i%3===0)plant(aisleX(row)+(i%2?1:-1)*(1.02+rng()*.27),z,.35+rng()*.38);
  }
  // Wild shoulders are taller and uneven; keep the cross-road and station clear.
  for(let i=0;i<9000;i++) {
    const side=i%2?1:-1,x=side*(22.2+rng()*17),z=-34+rng()*47.8;
    const density=.5+.22*Math.sin(x*.7+z*.3)+.2*Math.sin(z*.9);
    if(rng()>density)continue;
    plant(x,z,.65+rng()*1.1,true);
  }
  for(let i=0;i<2500;i++)plant(-38+rng()*76,-21-rng()*17,.65+rng(),true);
  const dummy=new THREE.Object3D(),color=new THREE.Color();
  groups.forEach((plants,index)=>{
    const mesh=new THREE.InstancedMesh(grassClump(81+index*31),mat,plants.length);
    plants.forEach((p,i)=>{
      dummy.position.set(p.x,.014,p.z);dummy.rotation.set(0,p.rotation,0);dummy.scale.set(p.width,p.height,p.width);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);
      color.setHSL(.19+p.patch*.045,p.edge?.24:.3,.34+p.patch*.12);mesh.setColorAt(i,color);
    });mesh.receiveShadow=true;mesh.computeBoundingSphere();scene.add(mesh);
  });
  // Small flower heads, each carried on an actual stem, punctuate the wild margins.
  const stems=new THREE.InstancedMesh(new THREE.CylinderGeometry(.006,.009,1,3),new THREE.MeshLambertMaterial({color:0x707d44}),380);
  const flowers=new THREE.InstancedMesh(new THREE.SphereGeometry(.05,5,3),new THREE.MeshLambertMaterial({color:0xe5dcc0}),380);
  for(let i=0;i<380;i++){
    const x=(i%2?1:-1)*(22.5+rng()*5),z=-20+rng()*33,h=.2+rng()*.24;
    dummy.position.set(x,h/2,z);dummy.rotation.set(0,rng()*6.28,0);dummy.scale.set(1,h,1);dummy.updateMatrix();stems.setMatrixAt(i,dummy.matrix);
    dummy.position.y=h;dummy.scale.set(1,.4,1);dummy.updateMatrix();flowers.setMatrixAt(i,dummy.matrix);
  }
  scene.add(stems,flowers);
  return {wind(time,enabled){clock.value=enabled?time:0;}};
}
