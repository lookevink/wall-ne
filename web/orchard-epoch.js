import * as THREE from 'three';

// Operator-view time of day. Decision cameras render under the calibrated
// afternoon look (calibrated()), so mission images never depend on the hour.
// Night lamps and wet-soil decals live on layer 1, which sensor cameras exclude.
const smooth=(a,b,x)=>THREE.MathUtils.smoothstep(x,a,b), lerp=THREE.MathUtils.lerp;
const linear=(r,g,b)=>new THREE.Color(r,g,b);
// Keyframes by solar elevation (degrees). Sky colors are linear shader values.
const KEYS=[
  {el:-18,zenith:linear(.006,.011,.03),horizon:linear(.018,.028,.06),hemiSky:0x24345a,hemiGround:0x110f0c,hemi:.75},
  {el:-9,zenith:linear(.03,.045,.11),horizon:linear(.09,.09,.16),hemiSky:0x3a4766,hemiGround:0x17140f,hemi:.8},
  {el:-3,zenith:linear(.10,.14,.29),horizon:linear(.55,.36,.31),hemiSky:0x7a7690,hemiGround:0x3b2f22,hemi:.9},
  {el:3,zenith:linear(.20,.33,.53),horizon:linear(.95,.66,.45),hemiSky:0xc9b9a4,hemiGround:0x6a5638,hemi:1.35},
  {el:12,zenith:linear(.27,.47,.62),horizon:linear(.86,.78,.62),hemiSky:0xdbe2da,hemiGround:0x84704e,hemi:1.75},
  {el:28,zenith:linear(.32,.53,.64),horizon:linear(.77,.79,.70),hemiSky:0xe4edec,hemiGround:0x8c7854,hemi:2},
];
const CALIBRATED={unlit:1,
  sun:new THREE.Vector3(-28,32,22),sunColor:new THREE.Color(0xffe6c1),sunIntensity:3.3,
  hemiSky:new THREE.Color(0xe4edec),hemiGround:new THREE.Color(0x8c7854),hemi:2,
  fog:new THREE.Color(0xd5d6bd),near:95,far:330,
  sky:{sunDirection:new THREE.Vector3(-.6,.45,.6),moonDirection:new THREE.Vector3(.4,.5,-.6),zenith:linear(.32,.53,.64),horizon:linear(.77,.79,.70),
    glow:linear(.28,.19,.08),wideGlow:linear(0,0,0),haze:.18,stars:0,sunDisc:0,moonDisc:0,mist:0},
};
function keyed(el){
  const found=KEYS.findIndex(k=>k.el>=el),upper=found<0?KEYS.length-1:found,hi=KEYS[upper],lo=KEYS[Math.max(0,upper-1)];
  const t=hi===lo?1:THREE.MathUtils.clamp((el-lo.el)/(hi.el-lo.el),0,1);
  return {zenith:lo.zenith.clone().lerp(hi.zenith,t),horizon:lo.horizon.clone().lerp(hi.horizon,t),
    hemiSky:new THREE.Color(lo.hemiSky).lerp(new THREE.Color(hi.hemiSky),t),hemiGround:new THREE.Color(lo.hemiGround).lerp(new THREE.Color(hi.hemiGround),t),hemi:lerp(lo.hemi,hi.hemi,t)};
}
function wetTexture(){
  const c=document.createElement('canvas');c.width=c.height=128;const ctx=c.getContext('2d');
  const fade=ctx.createRadialGradient(64,64,4,64,64,63);fade.addColorStop(0,'rgba(48,37,24,.62)');fade.addColorStop(.62,'rgba(56,44,28,.45)');fade.addColorStop(1,'rgba(60,48,30,0)');
  ctx.fillStyle=fade;ctx.fillRect(0,0,128,128);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t;
}

export class Atmosphere {
  constructor(view){
    this.view=view;this.sky=view.landscape.sky.uniforms;this.previous=null;this.current=null;this.receivedAt=0;this.interval=650;this.night=false;
    this.lamps=[];this.unlit=new Map();this.own=new Set();
    for(const robot of Object.values(view.robots)){
      // Forward is -z on the rover body; lamps ride with its heading.
      const lamp=new THREE.SpotLight(0xfff0d2,0,22,.62,.55,1.4);lamp.position.set(0,.95,-1.05);lamp.target.position.set(0,0,-8);
      const lens=new THREE.Mesh(new THREE.BoxGeometry(.5,.07,.03),new THREE.MeshBasicMaterial({color:0x2b2a26}));lens.position.set(0,.84,-1.02);
      robot.add(lamp,lamp.target,lens);this.lamps.push({light:lamp,lens,peak:14});this.own.add(lens.material);
    }
    for(const [x,y,z,peak] of [[-6,2.9,21.5,9],[6,2.9,21.5,9],[-27,2.7,23.1,6]]){
      const light=new THREE.PointLight(0xffcf94,0,16,1.6);light.position.set(x,y,z);light.layers.set(1);view.scene.add(light);this.lamps.push({light,peak});
    }
    for(const lamp of this.lamps){lamp.light.visible=false;lamp.light.layers.set(1);lamp.lens?.layers.set(1);}
    this.wet=new THREE.InstancedMesh(new THREE.CircleGeometry(1,40),new THREE.MeshBasicMaterial({map:wetTexture(),transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-2}),10);
    this.own.add(this.wet.material);this.wet.rotation.x=-Math.PI/2;this.wet.position.y=.022;this.wet.count=0;this.wet.layers.set(1);this.wet.frustumCulled=false;view.scene.add(this.wet);
  }
  update(epoch){
    if(!epoch)return;
    this.previous=this.current?this.sample(performance.now()):null;this.current=epoch;this.receivedAt=performance.now();
    const dummy=new THREE.Object3D(),trees=epoch.trees||[];this.wet.count=trees.length;
    trees.forEach((tree,i)=>{
      // Basin decals follow measured soil moisture; dry soil shows only the root shade.
      const r=.95*THREE.MathUtils.clamp((tree.moisture-12)/53,0,1);
      dummy.position.set(tree.position[0],-tree.position[2],0);dummy.scale.set(Math.max(r,.001),Math.max(r,.001),1);dummy.updateMatrix();this.wet.setMatrixAt(i,dummy.matrix);
    });
    this.wet.instanceMatrix.needsUpdate=true;
    // Unlit surfaces (root shade, weed foliage) would glow at night; track them to dim with daylight.
    // Keeps each material's calibrated color; materials of replaced specimens drop out.
    const seen=new Map();
    this.view.scene.traverse(o=>{const m=o.material;if(o.isMesh&&m?.isMeshBasicMaterial&&!this.own.has(m))seen.set(m,this.unlit.get(m)||m.color.clone());});
    this.unlit=seen;
  }
  // Applies one epoch exactly, without easing; offline film frames depend only on their state.
  set(epoch){this.update(epoch);this.previous=null;this.tick(this.receivedAt);}
  // Ease between the last two server samples so the sun never steps.
  sample(now){
    const c=this.current;if(!c)return null;const p=this.previous;
    const t=p?THREE.MathUtils.clamp((now-this.receivedAt)/this.interval,0,1):1;
    const mix=(a,b)=>lerp(a,b,t),dir=(a,b)=>new THREE.Vector3(...a).lerp(new THREE.Vector3(...b),t).normalize();
    const from=p&&p.day===c.day?p:c;
    return {...c,sun:{elevation:mix(from.sun.elevation,c.sun.elevation),direction:dir(from.sun.direction,c.sun.direction).toArray()},
      moon:{elevation:c.moon.elevation,direction:dir(from.moon.direction,c.moon.direction).toArray()},
      humidity:mix(from.humidity,c.humidity),mist:mix(from.mist,c.mist)};
  }
  tick(now){
    const env=this.sample(now);if(!env)return;this.look=this.lookFor(env);this.apply(this.look);
    const night=env.sun.elevation<-1.5;
    if(night!==this.night){this.night=night;for(const lamp of this.lamps)lamp.light.visible=night;}
    const glow=1-smooth(-4,-1,env.sun.elevation);
    for(const lamp of this.lamps){lamp.light.intensity=lamp.peak*glow;lamp.lens?.material.color.setHex(night?0xfff3d6:0x2b2a26);}
  }
  lookFor(env){
    const el=env.sun.elevation,k=keyed(el),cloud=env.cloud||0,sun=new THREE.Vector3(...env.sun.direction),moon=new THREE.Vector3(...env.moon.direction);
    const golden=1-smooth(3,24,el),daylight=smooth(-4,8,el),moonlight=1-smooth(-12,-6,el);
    const fogAmount=THREE.MathUtils.clamp(env.mist+.25*THREE.MathUtils.clamp((env.humidity-45)/45,0,1),0,1);
    const useSun=el>-6,light=(useSun?sun:moon).clone().multiplyScalar(48);
    const overcast=1-.45*cloud,gray=new THREE.Color(.42,.44,.46).multiplyScalar(Math.max(.05,daylight));
    const zenith=k.zenith.clone().lerp(gray,cloud*.5),horizon=k.horizon.clone().lerp(gray.clone().multiplyScalar(1.6),cloud*.4);
    return {
      sun:light,sunColor:new THREE.Color(0xffe6c1).lerp(new THREE.Color(0xff9a52),golden*daylight).lerp(new THREE.Color(0xa7bde8),useSun?0:1),
      sunIntensity:useSun?3.3*daylight*overcast:.85*moonlight*(1-cloud*.6),
      hemiSky:k.hemiSky,hemiGround:k.hemiGround,hemi:k.hemi*(1+.15*cloud),unlit:THREE.MathUtils.clamp(k.hemi/2*(.35+.65*daylight),.06,1),
      fog:horizon.clone(),fogLinear:true,near:lerp(95,8,fogAmount),far:lerp(330,70,fogAmount),
      sky:{sunDirection:sun,moonDirection:moon,zenith,horizon,glow:new THREE.Color(.28,.19,.08).lerp(new THREE.Color(.55,.24,.06),golden).multiplyScalar(daylight*overcast+.15*(1-smooth(-8,-1,el))*smooth(-14,-6,el)),
        wideGlow:new THREE.Color(.42,.2,.07).multiplyScalar(golden*smooth(-7,1,el)*(1-cloud)),haze:.18*daylight,
        stars:(1-smooth(-12,-5,el))*(1-cloud)*(1-env.mist),sunDisc:smooth(-1,2,el)*(1-cloud),moonDisc:moonlight*(1-cloud*.8),mist:env.mist},
    };
  }
  apply(look){
    const v=this.view;
    v.sun.position.copy(look.sun);v.sun.color.copy(look.sunColor);v.sun.intensity=look.sunIntensity;
    v.hemi.color.copy(look.hemiSky);v.hemi.groundColor.copy(look.hemiGround);v.hemi.intensity=look.hemi;
    if(look.fogLinear)v.scene.fog.color.setRGB(look.fog.r,look.fog.g,look.fog.b,THREE.LinearSRGBColorSpace);else v.scene.fog.color.copy(look.fog);
    v.scene.fog.near=look.near;v.scene.fog.far=look.far;
    for(const [m,color] of this.unlit)m.color.copy(color).multiplyScalar(look.unlit);
    for(const [key,value] of Object.entries(look.sky)){const u=this.sky[key];if(u.value?.copy)u.value.copy(value);else u.value=value;}
  }
  // Renders fn under the calibrated lighting the sensor pipeline was validated with.
  // Without shadows, the pass reuses the current shadow map and leaves any pending refresh for the next view.
  calibrated(fn,{shadows=true}={}){
    const map=this.view.renderer.shadowMap,pending=map.needsUpdate;this.apply(CALIBRATED);map.needsUpdate=shadows;
    try{return fn();}finally{if(this.look)this.apply(this.look);map.needsUpdate=shadows||pending;}
  }
}
