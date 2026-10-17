import * as THREE from 'three';
import {fieldRover} from './field-rover.js';
import {landscape} from './orchard-landscape.js';
import {orchard} from './orchard-trees.js';
import {TREE_COUNT,aisleX} from './orchard-layout.js';

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
    this.scene=new THREE.Scene();this.scene.fog=new THREE.Fog(0xd8ddcc,65,180);
    this.camera=new THREE.PerspectiveCamera(43,1,.1,250);
    this.scene.add(new THREE.HemisphereLight(0xe4edec,0x8c7854,2));
    const sun=new THREE.DirectionalLight(0xffe6c1,3.3);sun.position.set(-28,32,22);sun.castShadow=true;
    sun.shadow.mapSize.set(2048,2048);sun.shadow.bias=-.00025;sun.shadow.normalBias=.045;
    Object.assign(sun.shadow.camera,{left:-43,right:43,top:43,bottom:-43,near:1,far:120});this.scene.add(sun);
    landscape(this.scene);this.trees=orchard(this.scene);
    this.robots={};this.feedCameras={};
    for(const id of ['W1','W2','W3','W4','W5','R1']) {
      const mesh=fieldRover(id);this.scene.add(mesh);this.robots[id]=mesh;
      this.feedCameras[id]=new THREE.PerspectiveCamera(65,16/9,.1,150);
    }
    this.zones={};this.expanded=null;this.windEnabled=!matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.paused=false;this.last=0;this.frames=0;this.statsAt=performance.now();this.fps=0;
    this.target=new THREE.Vector3(0,0,0);this.orbit={theta:.56,phi:.73,radius:69};this.bindNavigation();this.setView('overview');
    this.resize();new ResizeObserver(()=>this.resize()).observe(element);
  }
  get expanded() { return this._expanded; }
  set expanded(value) {
    this._expanded=value;
    const stamp=this.element.querySelector('.orchard-stamp');
    if(stamp){
      stamp.querySelector('span').textContent=value?`ONBOARD / ${value}`:'PRUNUS DULCIS / 13 × 13';
      stamp.querySelector('strong').textContent=value?'A rover’s view of the orchard.':`${TREE_COUNT} trees. One shared home.`;
      stamp.querySelector('small').textContent=value?'Press Escape to return to the orchard':'Drag to explore · Scroll to get closer';
    }
    const compass=this.element.querySelector('.compass');if(compass)compass.hidden=Boolean(value);
    this.element.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(!value&&b.dataset.view===(this.currentView||'overview'))));
  }
  setView(name) {
    this.currentView=name;this.expanded=null;
    if(name==='rows') { this.target.set(aisleX(5),.4,-8);this.orbit={theta:0,phi:1.5,radius:20}; }
    else if(name==='depot') {this.target.set(-1,1,20);this.orbit={theta:.6,phi:1.13,radius:22};}
    else {this.target.set(0,0,1);this.orbit={theta:.56,phi:.73,radius:this.element.clientWidth<600?77:69};}
    this.positionCamera();
    this.element.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===name)));
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
    this.element.querySelector('#overview')?.addEventListener('click',()=>this.setView('overview'));
    this.element.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>this.setView(b.dataset.view)));
  }
  resize() {
    this.renderer.setSize(this.element.clientWidth,this.element.clientHeight,false);this.camera.aspect=this.element.clientWidth/this.element.clientHeight;this.camera.updateProjectionMatrix();
  }
  update(state) {
    for(const [id,v] of Object.entries(state.vehicles)) {
      const m=this.robots[id];m.position.set(v.position[0],0,v.position[1]);const next=v.action?.route?.[0];
      if(next)m.rotation.y=Math.atan2(next[0]-v.position[0],next[1]-v.position[1])+Math.PI;
      const c=this.feedCameras[id];c.position.set(v.position[0],1.6,v.position[1]-.5);
      const forward=new THREE.Vector3(0,-.15,-1).applyAxisAngle(new THREE.Vector3(0,1,0),m.rotation.y);c.lookAt(c.position.clone().add(forward));m.visible=v.lifecycle!=='spare';
    }
    for(const [id,z] of Object.entries(state.zones)) {
      if(!this.zones[id]) {
        const mesh=new THREE.Mesh(new THREE.RingGeometry(.53,.62,32),new THREE.MeshBasicMaterial({color:0xb5ab7b,transparent:true,opacity:.8,depthWrite:false}));
        mesh.rotation.x=-Math.PI/2;mesh.position.set(z.position[0],.055,z.position[1]);this.scene.add(mesh);this.zones[id]=mesh;
      }
      this.zones[id].material.color.setHex(z.observed===null?0xb5ab7b:z.moisture>=65?0x6ea7a0:z.initial<=30?0xd0874f:0x90a273);
    }
  }
  draw(time) {
    if(this.paused||document.hidden||time-this.last<1000/30)return false;
    this.last=time-(time-this.last)%(1000/30);this.trees.wind(time/1000,this.windEnabled);
    this.renderer.shadowMap.autoUpdate=false;this.renderer.shadowMap.needsUpdate=time-(this.lastShadow||0)>100;
    if(this.renderer.shadowMap.needsUpdate)this.lastShadow=time;
    this.renderer.setRenderTarget(null);
    const active=this.expanded?this.feedCameras[this.expanded]:this.camera;
    if(this.expanded){active.aspect=this.camera.aspect;active.updateProjectionMatrix();}
    this.renderer.render(this.scene,active);
    if(this.expanded){active.aspect=16/9;active.updateProjectionMatrix();}
    this.frames++;if(time-this.statsAt>1000){this.fps=this.frames*1000/(time-this.statsAt);this.frames=0;this.statsAt=time;}return true;
  }
}
