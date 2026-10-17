import * as THREE from 'three';
import {fieldRover} from './field-rover.js';
import {landscape} from './orchard-landscape.js';
import {orchard} from './orchard-trees.js';
import {OrchardArm} from './orchard-arm.js';
import {Atmosphere} from './orchard-epoch.js';

export class FleetScene {
  constructor(element) {
    this.element=element;
    this.renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));
    const gl=this.renderer.getContext(), debug=gl.getExtension('WEBGL_debug_renderer_info');
    this.backend=debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
    this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    this.renderer.setClearColor(0xd8ddcc);this.renderer.outputColorSpace=THREE.SRGBColorSpace;
    this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.12;
    element.prepend(this.renderer.domElement);
    this.scene=new THREE.Scene();this.scene.fog=new THREE.Fog(0xd5d6bd,95,330);
    this.camera=new THREE.PerspectiveCamera(43,1,.1,700);
    this.hemi=new THREE.HemisphereLight(0xe4edec,0x8c7854,2);this.scene.add(this.hemi);
    const sun=this.sun=new THREE.DirectionalLight(0xffe6c1,3.3);sun.position.set(-28,32,22);sun.castShadow=true;
    sun.shadow.mapSize.set(2048,2048);sun.shadow.bias=-.00025;sun.shadow.normalBias=.045;
    Object.assign(sun.shadow.camera,{left:-43,right:43,top:43,bottom:-43,near:1,far:120});this.scene.add(sun);
    this.landscape=landscape(this.scene);this.trees=orchard(this.scene);
    this.robots={};this.feedCameras={};
    for(const id of ['W1','W2','W3','W4','W5','R1']) {
      const mesh=fieldRover(id);this.scene.add(mesh);this.robots[id]=mesh;
      this.feedCameras[id]=new THREE.PerspectiveCamera(65,16/9,.1,700);
    }
    this.camera.layers.enable(1);
    for(const camera of Object.values(this.feedCameras))camera.layers.enable(1);
    this.feedCameras.WRIST=new THREE.PerspectiveCamera(70,16/9,.05,30);
    this.armControl=new OrchardArm(this);this.atmosphere=new Atmosphere(this);
    this.expanded=null;this.windEnabled=!matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.paused=false;this.last=0;this.frames=0;this.statsAt=performance.now();this.fps=0;
    this.target=new THREE.Vector3(0,0,0);this.orbit={theta:.56,phi:.73,radius:69};this.bindNavigation();this.setView('overview');
    this.resize();new ResizeObserver(()=>this.resize()).observe(element);
  }
  get expanded() { return this._expanded; }
  set expanded(value) {
    this._expanded=value;
    this.renderer.domElement.setAttribute('aria-label',value?`Onboard camera ${value}. Select Master view or press Escape to return.`:'Master view. Drag to orbit, scroll to zoom. Arrow keys orbit; plus and minus zoom.');
    this.element.dispatchEvent(new Event('viewchange'));
    const compass=this.element.querySelector('.compass');if(compass)compass.hidden=Boolean(value);
  }
  setView() {
    this.currentView='overview';this.expanded=null;
    this.target.set(0,2,-5);this.orbit={theta:.56,phi:1.25,radius:77};
    this.resize();this.positionCamera();
  }
  positionCamera() {
    const {theta,phi,radius}=this.orbit;
    this.camera.position.set(this.target.x+radius*Math.sin(phi)*Math.sin(theta),this.target.y+radius*Math.cos(phi),this.target.z+radius*Math.sin(phi)*Math.cos(theta));
    this.camera.lookAt(this.target);
    const north=this.element.querySelector('.compass span');if(north)north.style.transform=`rotate(${theta}rad)`;
  }
  bindNavigation() {
    const canvas=this.renderer.domElement;canvas.tabIndex=0;canvas.setAttribute('aria-label','Orchard view. Drag to orbit, scroll to zoom. Arrow keys orbit; plus and minus zoom.');
    let drag=null;
    canvas.addEventListener('pointerdown',e=>{if(this.expanded)return;drag={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!drag)return;this.orbit.theta-=(e.clientX-drag.x)*.006;this.orbit.phi=THREE.MathUtils.clamp(this.orbit.phi+(e.clientY-drag.y)*.005,.18,1.5);drag={x:e.clientX,y:e.clientY};this.positionCamera();});
    const release=()=>{drag=null;};canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',release);
    canvas.addEventListener('wheel',e=>{if(this.expanded)return;e.preventDefault();this.orbit.radius=THREE.MathUtils.clamp(this.orbit.radius*Math.exp(e.deltaY*.001),9,105);this.positionCamera();},{passive:false});
    canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-'].includes(e.key)||this.expanded)return;e.preventDefault();if(e.key==='ArrowLeft')this.orbit.theta-=.08;if(e.key==='ArrowRight')this.orbit.theta+=.08;if(e.key==='ArrowUp')this.orbit.phi-=.06;if(e.key==='ArrowDown')this.orbit.phi+=.06;if(e.key==='+'||e.key==='=')this.orbit.radius*=.9;if(e.key==='-')this.orbit.radius*=1.1;this.orbit.phi=THREE.MathUtils.clamp(this.orbit.phi,.18,1.5);this.orbit.radius=THREE.MathUtils.clamp(this.orbit.radius,9,105);this.positionCamera();});
  }
  resize() {
    this.renderer.setSize(this.element.clientWidth,this.element.clientHeight,false);this.camera.aspect=this.element.clientWidth/this.element.clientHeight;this.camera.fov=this.currentView==='overview'?THREE.MathUtils.radToDeg(2*Math.atan(Math.tan(THREE.MathUtils.degToRad(43)/2)/Math.min(1,this.camera.aspect))):43;this.camera.updateProjectionMatrix();
  }
  update(state) {
    this.orchardMission=state.arena==='orchard';
    for(const [id,v] of Object.entries(state.vehicles)) {
      const m=this.robots[id];m.position.set(v.position[0],0,v.position[1]);const next=v.action?.route?.[0];
      if(next)m.rotation.y=Math.atan2(next[0]-v.position[0],next[1]-v.position[1])+Math.PI;
      if(this.orchardMission&&(id==='W1'||state.mission_type==='fleet_care'))m.rotation.y=0;
      m.traverse(object=>object.layers.set(this.orchardMission?1:0));
      const c=this.feedCameras[id];c.position.set(v.position[0],1.6,v.position[1]-.5);
      const forward=new THREE.Vector3(0,-.15,-1).applyAxisAngle(new THREE.Vector3(0,1,0),m.rotation.y);c.lookAt(c.position.clone().add(forward));m.visible=v.lifecycle!=='spare';
    }
    this.armControl.update(state);this.atmosphere.update(state.epoch);
    if(!this.orchardMission&&this.expanded==='WRIST')this.expanded=null;
  }

  draw(time) {
    if(this.paused||document.hidden||time-this.last<1000/30)return false;
    this.last=time-(time-this.last)%(1000/30);this.trees.wind(time/1000,this.windEnabled&&!this.orchardMission);this.landscape.wind(time/1000,this.windEnabled&&!this.orchardMission);
    this.renderer.shadowMap.autoUpdate=false;this.renderer.shadowMap.needsUpdate||=time-(this.lastShadow||0)>100;
    if(this.renderer.shadowMap.needsUpdate)this.lastShadow=time;
    this.renderer.setRenderTarget(null);
    const active=this.expanded?this.feedCameras[this.expanded]:this.camera;
    if(this.expanded){active.aspect=this.camera.aspect;active.updateProjectionMatrix();}
    this.renderer.render(this.scene,active);
    if(this.expanded){active.aspect=16/9;active.updateProjectionMatrix();}
    this.frames++;if(time-this.statsAt>1000){this.fps=this.frames*1000/(time-this.statsAt);this.frames=0;this.statsAt=time;}return true;
  }
}
