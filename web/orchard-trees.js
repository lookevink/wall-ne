import * as THREE from 'three';
import {Tree} from '@dgreenheck/ez-tree';
import {skeleton, random} from './almond-geometry.js';
import {barkTexture, leafGeometry, leafTexture, hullTexture} from './almond-textures.js';
import {cylinder, material} from './static-geometry.js';
import {batchStatic} from './batch-geometry.js';
import {ORCHARD,planting,rowX} from './orchard-layout.js';
import {almondTrunkGeometry} from './almond-trunk.js';

function windMaterial(mat, clock, strength) {
  mat.onBeforeCompile = shader => {
    shader.uniforms.orchardTime = clock;
    shader.uniforms.orchardWind = strength;
    shader.vertexShader = 'uniform float orchardTime;\nuniform float orchardWind;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `
      #include <begin_vertex>
      #ifdef USE_INSTANCING
      vec3 anchor = instanceMatrix[3].xyz;
      float breeze = sin(orchardTime * 1.3 + anchor.x * .8 + anchor.z * .5);
      transformed.z += orchardWind * breeze * .035 * (position.y + .2);
      transformed.x += orchardWind * sin(orchardTime * 2.1 + anchor.z) * .012;
      #endif
    `);
  };
  mat.customProgramCacheKey = () => 'almond-breeze-v2';
  return mat;
}
export function orchard(scene) {
  const group = new THREE.Group(), rng = random(982), clock = {value:0},strength={value:0},windVector={value:new THREE.Vector3()};let sensorMode=false;
  const bark = material(0xd2c2a5); bark.map = barkTexture(); bark.bumpMap = bark.map; bark.bumpScale = .035;
  const leaf = windMaterial(new THREE.MeshStandardMaterial({map:leafTexture(), color:0xc1ce8e, roughness:.83, side:THREE.DoubleSide}), clock,strength);
  const hull = new THREE.MeshStandardMaterial({map:hullTexture(), roughness:1});
  const leafShape = leafGeometry(), hullShape = new THREE.SphereGeometry(.067, 7, 6);
  const variants = Array.from({length:ORCHARD.variants},(_,i)=>71+i*17).map(seed => {
    const data = skeleton(seed), wood = new THREE.Group();
    wood.add(new THREE.Mesh(almondTrunkGeometry(),bark));
    for (const [a,b,r1,r2] of data.branches) cylinder(wood, a,b,r1,r2,bark, r1 > .05 ? 7 : 4);
    batchStatic(wood);
    const geometry = wood.children.find(o => o.isMesh).geometry;
    return {data, geometry, transforms:[]};
  });
  const dummy = new THREE.Object3D(), color = new THREE.Color();
  const leaves = [], hulls = [], trees=planting();
  group.userData.treeCount=trees.length;group.userData.variantCount=variants.length;
  for (let row = 0; row < ORCHARD.rows; row++) {
    const leafData = [], hullData = [];
    for (const tree of trees.filter(t=>t.row===row)) {
      const variant=variants[tree.variant];
      dummy.position.set(...tree.position);dummy.rotation.set(0,tree.rotation,0);dummy.scale.set(...tree.scale);dummy.updateMatrix();
      const treeMatrix=dummy.matrix.clone();variant.transforms.push({matrix:treeMatrix,tone:tree.barkTone});
      for (const l of variant.data.leaves) {
        dummy.position.set(...l.position); dummy.rotation.set(...l.rotation); dummy.scale.setScalar(l.scale*tree.leafScale); dummy.updateMatrix();
        leafData.push({matrix:new THREE.Matrix4().multiplyMatrices(treeMatrix,dummy.matrix), tint:l.tint,hue:tree.hue,saturation:tree.saturation,lightness:tree.lightness});
      }
      for (const h of variant.data.hulls) {
        dummy.position.set(...h.position); dummy.rotation.set(.2,h.rotation,.2); dummy.scale.set(.65,1.3,.8); dummy.updateMatrix();
        hullData.push(new THREE.Matrix4().multiplyMatrices(treeMatrix,dummy.matrix));
      }
    }
    const foliage = new THREE.InstancedMesh(leafShape,leaf,leafData.length);
    leafData.forEach((l,i) => { foliage.setMatrixAt(i,l.matrix); color.setHSL(l.hue+(l.tint-.5)*.015,l.saturation,l.lightness+l.tint*.15); foliage.setColorAt(i,color); });
    foliage.castShadow = true; foliage.receiveShadow = true; foliage.computeBoundingSphere(); group.add(foliage); leaves.push(foliage);
    const fruit = new THREE.InstancedMesh(hullShape,hull,hullData.length);
    hullData.forEach((matrix,i) => fruit.setMatrixAt(i,matrix)); fruit.computeBoundingSphere();
    const center = new THREE.Vector3(rowX(row),2,-1);
    // Subpixel fruit adds no detail to the overview; each onboard view gets nearby fruit.
    fruit.onBeforeRender = (_r,_s,camera) => { fruit.count = sensorMode||camera.position.distanceTo(center) < 32 ? hullData.length : 0; };
    fruit.userData.fullCount=hullData.length;
    group.add(fruit); hulls.push(fruit);
  }
  for (const variant of variants) {
    const wood = new THREE.InstancedMesh(variant.geometry,bark,variant.transforms.length);
    variant.transforms.forEach((t,i) => {wood.setMatrixAt(i,t.matrix);wood.setColorAt(i,color.setScalar(t.tone));}); wood.castShadow = wood.receiveShadow = true; group.add(wood);
  }
  // Three seeded windbreak forms. Keep EZ-Tree's original asset attribution.
  for (let v = 0; v < 3; v++) {
    const tree = new Tree(); tree.loadPreset('Oak Small'); tree.options.seed = 87 + v;
    tree.options.branch.levels = 3; tree.options.leaves.count = 8; tree.options.leaves.size = 2.8; tree.generate();
    const matrices=[];
    for (let i = v; i < 22; i += 3) {
      dummy.position.set(-33 + i * 3.2,0,-24-rng()*3);
      dummy.rotation.set(0,rng()*6.28,0); dummy.scale.setScalar(.24+rng()*.1);dummy.updateMatrix();matrices.push(dummy.matrix.clone());
    }
    // EZ-Tree replaces project_vertex; restore the instance transform it omits.
    const compileWind=tree.leavesMesh.material.onBeforeCompile;
    tree.leavesMesh.material.onBeforeCompile=shader=>{
      compileWind(shader);shader.uniforms.uTime=clock;shader.uniforms.uWindStrength=windVector;
      shader.vertexShader=shader.vertexShader.replace('mvPosition = modelViewMatrix * mvPosition;', `
        #ifdef USE_INSTANCING
        mvPosition = instanceMatrix * mvPosition;
        #endif
        mvPosition = modelViewMatrix * mvPosition;`);
    };
    tree.leavesMesh.material.customProgramCacheKey=()=> 'instanced-ez-tree-wind-v1';
    for (const source of [tree.branchesMesh,tree.leavesMesh]) {
      const mesh=new THREE.InstancedMesh(source.geometry,source.material,matrices.length);
      matrices.forEach((matrix,i)=>mesh.setMatrixAt(i,matrix));mesh.castShadow=mesh.receiveShadow=true;group.add(mesh);
    }
  }
  scene.add(group);
  return {group, leaves, hulls, count:trees.length,
    sensorMode(enabled){sensorMode=enabled;if(enabled)for(const hull of hulls)hull.count=hull.userData.fullCount;},
    wind(time,enabled) { clock.value = enabled ? time : 0;strength.value=enabled?1:0;windVector.value.setScalar(enabled?.5:0); }};
}
