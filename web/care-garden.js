import * as THREE from 'three';
import {weedMesh,cloverMesh,disposeSpecimen} from './weed-geometry.js';
import {caterpillarMesh,ladybirdMesh} from './insect-geometry.js';

export class Garden {
  constructor(scene) {this.group=new THREE.Group();scene.add(this.group);this.targets={};this.id=null;}
  update(state) {
    if(this.id!==state.id) {
      disposeSpecimen(this.group);this.group.clear();this.targets={};this.id=state.id;
      for(const w of state.weeds||(state.weed?[state.weed]:[])){const mesh=weedMesh(w);this.targets[w.id]=mesh;this.group.add(mesh);}
      for(const p of state.protected||[])this.group.add(cloverMesh(p));
      for(const p of state.pests||[]){const mesh=caterpillarMesh(p);this.targets[p.id]=mesh;this.group.add(mesh);}
      for(const p of state.beneficial||[])this.group.add(ladybirdMesh(p));
    }
    for(const w of state.weeds||(state.weed?[state.weed]:[]))if(this.targets[w.id])this.targets[w.id].visible=!w.removed;
    for(const p of state.pests||[])if(this.targets[p.id])this.targets[p.id].visible=!p.removed;
  }
}
