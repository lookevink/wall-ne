import * as THREE from 'three';
import {weedMesh,cloverMesh,disposeSpecimen} from './weed-geometry.js';
import {caterpillarMesh,ladybirdMesh} from './insect-geometry.js';
const profiles={
  rosette:{name:'Lobed rosette',subtitle:'Dandelion-inspired leaf architecture',description:'A low crown of overlapping leaves. Each blade has its own reach, curl and irregular lobes, with a raised midrib running back to the growing point.',features:[['FORM','Lobed blades · low central crown'],['DETAIL','Branching veins and folded young leaves']],note:'Find the growing point before reaching for a leaf.'},
  grass:{name:'Grass tuft',subtitle:'Folded blades, gathered at the base',description:'Slender blades rise from a compact tuft, then arch under their own shape. New blades remain upright; longer leaves bend outward in different directions.',features:[['FORM','Narrow folded blades · clustered shoots'],['BELOW GROUND','A fine, branching fibrous root system']],note:'Many blades. One rooted tuft.'},
  thistle:{name:'Spiny rosette',subtitle:'A thistle-inspired juvenile form',description:'Deeply cut leaf margins end in fine spines. Uneven lobes and a lifted central rib give each leaf a stiff, slightly cupped profile.',features:[['FORM','Lobed rosette · lifted crown'],['DETAIL','Fine marginal spines and visible veins']],note:'Look for the central stem, beneath the spiny leaves.'},
  caterpillar:{name:'Banded caterpillar',subtitle:'A study in larval anatomy',description:'A continuous, slightly curved body with soft folds between segments, a dark head capsule, small side spiracles and sparse hairs. Jointed legs sit near the head; fleshy prolegs support the abdomen.',features:[['FORM','Segmented body · distinct head capsule'],['DETAIL','Thoracic legs, prolegs and spiracles']],note:'Inspect the insect before choosing a treatment.'},
  clover:{name:'White-clover form',subtitle:'Three leaflets at the end of a stalk',description:'Small, rounded leaflets form groups of three on fine petioles. Pale chevrons follow the curved surface rather than floating above it.',features:[['FORM','Three rounded leaflets per petiole'],['DETAIL','Pale leaf markings · low spreading growth']],note:'Protected groundcover in this orchard. Leave it growing.',protected:true},
  ladybird:{name:'Ladybird beetle',subtitle:'A protected orchard companion',description:'Two glossy wing covers meet along a fine center seam. Beneath them are a dark body, six jointed legs, a separate head and short antennae.',features:[['FORM','Paired domed wing covers'],['DETAIL','Dark spots · six legs · short antennae']],note:'A beneficial insect in this simulation. Leave it undisturbed.',protected:true}
};
const viewport=document.querySelector('#specimen-viewport'),renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0xe3e6d5);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.25;renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;viewport.prepend(renderer.domElement);
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(37,1,.01,20),pivot=new THREE.Group();scene.add(pivot);
scene.add(new THREE.HemisphereLight(0xf4f3df,0x77795a,2));const light=new THREE.DirectionalLight(0xffeed1,3);light.position.set(-2,4,3);light.castShadow=true;light.shadow.mapSize.set(2048,2048);Object.assign(light.shadow.camera,{left:-1,right:1,top:1,bottom:-1,near:.1,far:10});light.shadow.normalBias=.002;scene.add(light);
const ground=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.MeshStandardMaterial({color:0xd7dcc6,roughness:1}));ground.rotation.x=-Math.PI/2;ground.position.y=-.006;ground.receiveShadow=true;scene.add(ground);
let current='rosette',specimen=null,roots=false,turning=false,yaw=.25,pitch=.58,distance=.85,previous=0,dirty=true;
const center=new THREE.Vector3(0,.1,0);let homeDistance=.85;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
function position(){camera.position.set(center.x+Math.sin(yaw)*distance*Math.cos(pitch),center.y+Math.sin(pitch)*distance,center.z+Math.cos(yaw)*distance*Math.cos(pitch));camera.lookAt(center);dirty=true;}
function fit(){
  specimen.updateMatrixWorld(true);const sphere=new THREE.Box3().setFromObject(specimen).getBoundingSphere(new THREE.Sphere());center.copy(sphere.center);
  const vertical=THREE.MathUtils.degToRad(camera.fov)/2,angle=Math.min(vertical,Math.atan(Math.tan(vertical)*camera.aspect));
  homeDistance=sphere.radius/Math.sin(angle)*1.16;distance=homeDistance;position();
}
function build(){
  if(specimen){disposeSpecimen(specimen);pivot.remove(specimen);}
  const spec={id:'study',form:current,position:[0,0,0],leaves:13,rotation:.73,size:1};
  if(current==='caterpillar'||current==='ladybird'){
    specimen=current==='caterpillar'?caterpillarMesh(spec):ladybirdMesh(spec);specimen.rotation.set(-Math.PI/2,0,Math.PI);specimen.scale.setScalar(current==='caterpillar'?2.8:5);specimen.position.y=.025;
  } else {specimen=current==='clover'?cloverMesh(spec):weedMesh(spec,{roots});if(current==='clover')specimen.scale.setScalar(1.6);}
  pivot.add(specimen);ground.visible=!roots;fit();dirty=true;
}
function select(key){
  current=key;roots=false;const p=profiles[key];
  document.querySelector('#name').textContent=p.name;document.querySelector('#subtitle').textContent=p.subtitle;document.querySelector('#description').textContent=p.description;document.querySelector('#care-note').textContent=p.note;document.querySelector('#role').textContent=p.protected?'PROTECTED IN THE ORCHARD':'MANAGEMENT TARGET';
  document.querySelector('#features').replaceChildren(...p.features.map(([label,value])=>{const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;row.append(dt,dd);return row;}));
  const keys=Object.keys(profiles);document.querySelector('#specimen-number').textContent=`SPECIMEN ${String(keys.indexOf(key)+1).padStart(2,'0')}`;
  document.querySelectorAll('[data-specimen]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.specimen===key)));
  document.querySelector('#roots').disabled=!['rosette','grass','thistle'].includes(key);document.querySelector('#roots').setAttribute('aria-pressed','false');build();position();
}
for(const b of document.querySelectorAll('[data-specimen]'))b.onclick=()=>select(b.dataset.specimen);
document.querySelector('#roots').onclick=()=>{roots=!roots;document.querySelector('#roots').setAttribute('aria-pressed',String(roots));build();};
document.querySelector('#rotate').onclick=()=>{turning=!turning;document.querySelector('#rotate').setAttribute('aria-pressed',String(turning));document.querySelector('#rotate').textContent=turning?'Stop turning':'Turn slowly';};
document.querySelector('#reset-view').onclick=()=>{yaw=.25;pitch=.58;distance=homeDistance;position();};
let drag=null;const canvas=renderer.domElement;canvas.tabIndex=0;canvas.setAttribute('aria-label','Specimen view. Drag or use arrow keys to turn. Plus and minus zoom.');
canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw-=(e.clientX-drag[0])*.01;pitch=THREE.MathUtils.clamp(pitch+(e.clientY-drag[1])*.008,-.45,1.35);drag=[e.clientX,e.clientY];position();});for(const type of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(type,()=>drag=null);
canvas.addEventListener('wheel',e=>{e.preventDefault();distance=THREE.MathUtils.clamp(distance*Math.exp(e.deltaY*.001),.5,2.5);position();},{passive:false});
canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-'].includes(e.key))return;e.preventDefault();if(e.key==='ArrowLeft')yaw-=.12;if(e.key==='ArrowRight')yaw+=.12;if(e.key==='ArrowUp')pitch+=.08;if(e.key==='ArrowDown')pitch-=.08;if(e.key==='+'||e.key==='=')distance*=.9;if(e.key==='-')distance*=1.1;pitch=THREE.MathUtils.clamp(pitch,-.45,1.35);distance=THREE.MathUtils.clamp(distance,.5,2.5);position();});
function resize(){renderer.setSize(viewport.clientWidth,viewport.clientHeight,false);camera.aspect=viewport.clientWidth/viewport.clientHeight;camera.updateProjectionMatrix();if(specimen)fit();dirty=true;}
new ResizeObserver(resize).observe(viewport);document.addEventListener('visibilitychange',()=>{previous=0;dirty=true;});reduced.addEventListener('change',()=>{turning=false;document.querySelector('#rotate').setAttribute('aria-pressed','false');document.querySelector('#rotate').textContent='Turn slowly';});
function draw(time){requestAnimationFrame(draw);if(document.hidden)return;if(turning&&!drag){yaw+=Math.min((time-previous)/1000,.05)*.17;position();}previous=time;if(dirty){renderer.render(scene,camera);dirty=false;}}
select(current);position();resize();requestAnimationFrame(draw);
