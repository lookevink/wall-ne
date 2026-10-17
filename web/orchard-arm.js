import * as THREE from 'three';
import {Garden} from './care-garden.js';
import {ManipulatorView} from './precision-manipulator.js';
import {calibratedCamera,sampleDepth} from './treatment-scene.js';

// These objects join the orchard scene itself; RGB and range use that same scene.
export class OrchardArm {
  constructor(view){this.view=view;this.garden=new Garden(view.scene);this.arm=new ManipulatorView(view.scene);this.arm.update({});this.camera=null;}
  update(state){
    const active=state.arena==='orchard';this.garden.group.visible=active;
    this.view.trees?.sensorMode(active);
    if(!active){this.arm.update({});return;}
    this.garden.update(state);
    const pose=state.observations.tool_pose;
    this.arm.update({arm:{...pose,orientation:pose.euler,grip:{opening:state.opening}},bin:{x:state.bin[0],y:state.bin[1],z:state.bin[2]}});
    const plant=this.garden.targets[state.weed.id];
    plant.position.set(state.weed.position[0],0,state.weed.position[2]);
    if(state.extracted&&(state.holding||state.deposited)){
      plant.visible=true;const point=state.holding?pose.position:state.bin;
      plant.position.set(point[0],point[1]-.08,point[2]);
    }
    this.camera=calibratedCamera(state.camera);this.view.feedCameras.WRIST=this.camera;
  }
  capture(config,canvas){
    const r=this.view.renderer,size=new THREE.Vector2();r.getSize(size);
    const ratio=r.getPixelRatio(),target=r.getRenderTarget(),camera=calibratedCamera(config);
    // Freeze shader wind for aligned RGB/depth; all orchard meshes remain present.
    this.view.trees.wind(0,false);this.view.landscape.wind(0,false);
    try{r.setRenderTarget(null);r.setPixelRatio(1);r.setSize(640,360,false);r.render(this.view.scene,camera);canvas.getContext('2d').drawImage(r.domElement,0,0);return canvas.toDataURL('image/png');}
    finally{r.setPixelRatio(ratio);r.setSize(size.x,size.y,false);r.setRenderTarget(target);}
  }
  depth(request){return sampleDepth(this.view.scene,request);}
}
