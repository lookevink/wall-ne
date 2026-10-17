// Transferred from FieldCrew; see docs/FIELDCREW.md for provenance.
import * as THREE from 'three';

export class ManipulatorView {
  constructor(scene){
    this.group=new THREE.Group();scene.add(this.group);
    const mat=color=>new THREE.MeshStandardMaterial({color,roughness:.55,metalness:.35});
    this.metal=mat('#d3cdbc');this.dark=mat('#394b4c');this.orange=mat('#de8c3b');
    this.links=Array.from({length:3},()=>{const m=new THREE.Mesh(new THREE.CylinderGeometry(.045,.055,1,12),this.metal);m.castShadow=true;this.group.add(m);return m;});
    this.joints=Array.from({length:6},()=>{const m=new THREE.Mesh(new THREE.SphereGeometry(.075,16,12),this.dark);this.group.add(m);return m;});
    this.hand=new THREE.Group();this.group.add(this.hand);
    const palm=new THREE.Mesh(new THREE.BoxGeometry(.17,.075,.085),this.orange);palm.position.y=.09;this.hand.add(palm);
    this.fingers=[-1,1].map(side=>{const f=new THREE.Mesh(new THREE.BoxGeometry(.018,.13,.04),this.dark);this.hand.add(f);f.userData.side=side;return f;});
    this.bin=new THREE.Group();scene.add(this.bin);
    for(const [size,pos] of [[[.55,.03,.55],[0,0,0]],[[.03,.28,.55],[-.275,.14,0]],[[.03,.28,.55],[.275,.14,0]],[[.55,.28,.03],[0,.14,-.275]],[[.55,.28,.03],[0,.14,.275]]]){
      const panel=new THREE.Mesh(new THREE.BoxGeometry(...size),this.dark);panel.position.set(...pos);this.bin.add(panel);
    }
  }
  update(s){
    this.group.visible=this.bin.visible=!!s.arm;if(!s.arm)return;
    const points=s.arm.points.map(p=>new THREE.Vector3(...p));
    for(let i=0;i<3;i++){
      const a=points[i],b=points[i+1],m=this.links[i];m.position.copy(a).lerp(b,.5);m.scale.y=a.distanceTo(b);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize());
    }
    // Three positioning joints and three independent wrist rotation axes.
    this.joints[0].position.copy(points[0]);this.joints[1].position.copy(points[0]).y+=.08;this.joints[2].position.copy(points[1]);
    for(let i=3;i<6;i++){this.joints[i].position.copy(points[2]).lerp(points[3],(i-3)*.27);this.joints[i].scale.setScalar(1-(i-3)*.15);}
    this.hand.position.copy(points[3]);this.hand.rotation.set(...s.arm.orientation.map(THREE.MathUtils.degToRad),'XYZ');
    for(const f of this.fingers)f.position.x=f.userData.side*(s.arm.grip.opening/2+.009);
    this.bin.position.set(s.bin.x,s.bin.y-.25,s.bin.z);
  }
}
