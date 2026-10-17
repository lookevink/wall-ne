// Compact wrist-camera manipulation geometry.
import * as THREE from 'three';

// Seeded plant architecture: separate curved blades, serrated broad leaves,
// petioles, branching stems and a root crown. No bitmap or repeated flat icon.
export function weedPlant(spec, seed=1) {
  let state=(seed+1)>>>0;
  const rand=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296;};
  const plant=new THREE.Group(), foliage=new THREE.MeshBasicMaterial({color:'#287a36',side:THREE.DoubleSide});
  const stemMaterial=new THREE.MeshStandardMaterial({color:'#456c29',roughness:1});
  const tube=(points,radius)=>{
    const curve=new THREE.CatmullRomCurve3(points);
    const stem=new THREE.Mesh(new THREE.TubeGeometry(curve,8,radius,5,false),stemMaterial);plant.add(stem);return stem;
  };
  const blade=(origin,angle,length,width,rise,serrated)=>{
    const positions=[],indices=[];
    for(let i=0;i<=12;i++){
      const t=i/12,radial=length*t,up=rise*Math.sin(t*Math.PI*.73);
      const edge=Math.sin(Math.PI*t)**.7*width*(serrated&&i%2?.62:1);
      for(const side of [-1,0,1]){
        const x=Math.sin(angle)*radial+Math.cos(angle)*edge*side;
        const z=Math.cos(angle)*radial-Math.sin(angle)*edge*side;
        positions.push(origin.x+x,origin.y+up+(side===0?.012*Math.sin(Math.PI*t):0),origin.z+z);
      }
      if(i<12){const a=i*3;indices.push(a,a+3,a+1,a+1,a+3,a+4,a+1,a+4,a+2,a+2,a+4,a+5);}
    }
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setIndex(indices);geometry.computeVertexNormals();
    plant.add(new THREE.Mesh(geometry,foliage));
    const tip=new THREE.Vector3(origin.x+Math.sin(angle)*length*.75,origin.y+rise*.98,origin.z+Math.cos(angle)*length*.75);
    tube([origin,origin.clone().lerp(tip,.5).add(new THREE.Vector3(0,.008,0)),tip],.0015);
  };
  const size=spec.size, count=spec.leaves;
  const crown=new THREE.Vector3(0,.085,0);
  tube([crown.clone().add(new THREE.Vector3(0,-.01,0)),crown.clone().add(new THREE.Vector3(.006,.05,0))],.009);
  for(let i=0;i<count;i++){
    const angle=i*2.39996+(rand()-.5)*.4;
    const grass=spec.form==='grass', thistle=spec.form==='thistle';
    const origin=crown.clone().add(new THREE.Vector3((rand()-.5)*.025,thistle?i/count*.17:rand()*.015,(rand()-.5)*.025));
    const length=(grass?.10+rand()*.10:.12+rand()*.13)*size;
    blade(origin,angle,length,(grass?.008+rand()*.008:.035+rand()*.025)*size,(grass?.20+rand()*.20:.035+rand()*.10)*size,!grass);
    if(thistle)tube([crown,origin],.004);
  }
  if(spec.form==='thistle'){
    const top=new THREE.Vector3(.025,.38*size,0);tube([crown,new THREE.Vector3(.01,.23,0),top],.005);
    const bud=new THREE.Mesh(new THREE.SphereGeometry(.025,8,6),foliage);bud.position.copy(top);plant.add(bud);
  }
  plant.rotation.y=spec.rotation;
  return plant;
}
