import * as THREE from 'three';

// A continuous landform, rising gently away from the flat cultivated block.
export function hillsGeometry() {
  const geo=new THREE.PlaneGeometry(480,270,120,90);geo.rotateX(-Math.PI/2);
  const p=geo.attributes.position,colors=[],terrainTone=new THREE.Color(0x929d75),earth=new THREE.Color(0xa99b78);
  for(let i=0;i<p.count;i++) {
    const x=p.getX(i),z=p.getZ(i)-160,distance=Math.max(0,-z-25),rise=1-Math.exp(-distance/45);
    const ridge=13+6*Math.sin(x*.023+z*.014)+5*Math.sin(x*.041-z*.018)+2*Math.cos(x*.079+z*.038);
    const h=rise*ridge;p.setXYZ(i,x,h-.055,z);
    const tint=.5+.25*Math.sin(x*.044+z*.061)+.15*Math.sin(x*.12-z*.08);
    const c=new THREE.Color().setHSL(.14+tint*.055,.18+tint*.08,.40+tint*.16);c.multiply(terrainTone).lerp(earth,Math.exp(-distance/18));colors.push(c.r,c.g,c.b);
  }
  geo.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geo.computeVertexNormals();return geo;
}
export function scenery(scene) {
  const hills=new THREE.Mesh(hillsGeometry(),new THREE.MeshLambertMaterial({vertexColors:true}));scene.add(hills);
  // Defaults reproduce the calibrated afternoon sky; the day cycle drives these uniforms.
  const uniforms={
    sunDirection:{value:new THREE.Vector3(-.6,.45,.6)},moonDirection:{value:new THREE.Vector3(.4,.5,-.6)},
    zenith:{value:new THREE.Color(.32,.53,.64)},horizon:{value:new THREE.Color(.77,.79,.70)},glow:{value:new THREE.Color(.28,.19,.08)},
    wideGlow:{value:new THREE.Color(0,0,0)},hazeColor:{value:new THREE.Color(.85,.86,.78)},
    haze:{value:.18},stars:{value:0},sunDisc:{value:0},moonDisc:{value:0},mist:{value:0},
  };
  const sky=new THREE.Mesh(new THREE.SphereGeometry(550,32,16),new THREE.ShaderMaterial({
    side:THREE.BackSide,depthWrite:false,uniforms,
    vertexShader:'varying vec3 skyDirection; void main(){skyDirection=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader:`varying vec3 skyDirection;
      uniform vec3 sunDirection,moonDirection,zenith,horizon,glow,wideGlow,hazeColor;
      uniform float haze,stars,sunDisc,moonDisc,mist;
      float hash(vec3 p){p=fract(p*.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
      void main(){
        vec3 d=normalize(skyDirection);
        float h=smoothstep(-.03,.7,d.y);
        vec3 color=mix(horizon,zenith,h);
        float sun=max(0.,dot(d,normalize(sunDirection)));
        color+=glow*pow(sun,18.);
        color+=wideGlow*pow(sun,3.)*(1.-h);
        color+=vec3(1.,.93,.78)*sunDisc*smoothstep(.99955,.9998,sun);
        float moon=max(0.,dot(d,normalize(moonDirection)));
        color+=vec3(.78,.83,.95)*moonDisc*(smoothstep(.99975,.99988,moon)+.08*pow(moon,40.));
        vec3 cell=floor(d*700.);
        color+=vec3(.86,.9,1.)*stars*step(.9982,hash(cell))*(.45+.55*hash(cell+3.1))*smoothstep(.03,.3,d.y);
        float ribbons=sin(d.x*18.+d.z*11.+sin(d.z*17.)*1.5)*.5+.5;
        float bands=smoothstep(.55,.95,ribbons)*smoothstep(.03,.18,d.y)*(1.-smoothstep(.28,.6,d.y));
        color=mix(color,hazeColor,bands*haze);
        color=mix(color,horizon,mist*.85*(1.-smoothstep(0.,.45,d.y)));
        gl_FragColor=vec4(color,1.);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`
  }));sky.frustumCulled=false;scene.add(sky);
  return {uniforms};
}
