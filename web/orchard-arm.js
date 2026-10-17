import * as THREE from 'three';
import {Garden} from './care-garden.js';
import {ManipulatorView} from './precision-manipulator.js';
import {calibratedCamera,sampleDepth} from './treatment-scene.js';

// These objects join the orchard scene itself; RGB and range use that same scene.
export class OrchardArm {
  constructor(view){this.view=view;this.garden=new Garden(view.scene);this.arm=new ManipulatorView(view.scene);this.arm.update({});this.camera=null;this.workers=new Map();}
  update(state){
    const active=state.arena==='orchard';this.garden.group.visible=active;
    this.view.trees?.sensorMode(active);
    if(state.mission_type==='fleet_care'){this.updateFleet(state);return;}
    for(const arm of this.workers.values())arm.update({});
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
  updateFleet(state){
    this.arm.update({});this.garden.update(state.care_inventory);
    for(const [worker,arm] of this.workers)if(!state.care_workers[worker])arm.update({});
    for(const [worker,s] of Object.entries(state.care_workers)){
      if(!this.workers.has(worker))this.workers.set(worker,new ManipulatorView(this.view.scene));
      const pose=s.observations.tool_pose;
      this.workers.get(worker).update({arm:{...pose,orientation:pose.euler,grip:{opening:s.opening}},bin:{x:s.bin[0],y:s.bin[1],z:s.bin[2]}});
      const plant=this.garden.targets[s.weed.id];
      if(plant){
        plant.position.set(s.weed.position[0],0,s.weed.position[2]);
        if(s.extracted&&(s.holding||s.deposited)&&s.unloaded_total<s.collected_total+Number(!s.stage_verified)){
          plant.visible=true;const point=s.holding?pose.position:s.bin;plant.position.set(point[0],point[1]-.08,point[2]);
        }
      }
      // Each worker tile shows its actual decision camera during care.
      this.view.feedCameras[worker]=calibratedCamera(s.camera);
    }
    const selected=state.care_workers[this.view.expanded]||Object.values(state.care_workers).find(s=>s.status==='running')||Object.values(state.care_workers)[0];
    if(selected)this.view.feedCameras.WRIST=calibratedCamera(selected.camera);
  }
  capture(config,canvas){
    const r=this.view.renderer,size=new THREE.Vector2();r.getSize(size);
    const ratio=r.getPixelRatio(),target=r.getRenderTarget(),camera=calibratedCamera(config);
    // Freeze shader wind for aligned RGB/depth; all orchard meshes remain present.
    this.view.trees.wind(0,false);this.view.landscape.wind(0,false);
    // Decision images keep the calibrated lighting at every hour of the orchard day.
    try{r.setRenderTarget(null);r.setPixelRatio(1);r.setSize(640,360,false);this.view.atmosphere.calibrated(()=>r.render(this.view.scene,camera));canvas.getContext('2d').drawImage(r.domElement,0,0);return canvas.toDataURL('image/png');}
    finally{r.setPixelRatio(ratio);r.setSize(size.x,size.y,false);r.setRenderTarget(target);}
  }
  depth(request){return sampleDepth(this.view.scene,request);}
}
