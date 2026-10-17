import * as THREE from 'three';

export class RoverViews {
  constructor(view,element) {
    this.view=view;this.feeds=[];this.last=0;this.rate=0;this.count=0;this.started=performance.now();
    // Reuse one HDR target and one display target for all five cameras.
    this.target=new THREE.WebGLRenderTarget(640,360,{type:THREE.HalfFloatType});
    this.output=new THREE.WebGLRenderTarget(640,360,{depthBuffer:false});
    this.pixels=new Uint8Array(640*360*4);
    this.displayScene=new THREE.Scene();this.displayCamera=new THREE.Camera();
    const display=new THREE.ShaderMaterial({
      uniforms:{frame:{value:this.target.texture},toneMappingExposure:{value:view.renderer.toneMappingExposure}},
      vertexShader:'varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}',
      fragmentShader:`uniform sampler2D frame; varying vec2 vUv;
        #include <tonemapping_pars_fragment>
        void main(){vec3 linear=texture2D(frame,vUv).rgb;gl_FragColor=sRGBTransferOETF(vec4(ACESFilmicToneMapping(linear),1.0));}`,
      depthTest:false,depthWrite:false,toneMapped:false
    });
    this.displayScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2,2),display));
    for(const id of ['W1','W2','W3','W4','W5']) {
      const tile=document.createElement('div');tile.className='feed';tile.tabIndex=0;tile.setAttribute('role','button');tile.setAttribute('aria-label',`Ride along with ${id}`);
      tile.innerHTML=`<canvas width="640" height="360"></canvas><div class="feed-title"><b>${id} / ONBOARD</b><span>RIDE ALONG ↗</span></div>`;
      const expand=()=>{view.expanded=id;view.element.scrollIntoView({block:'center',behavior:'instant'});};
      tile.onclick=expand;tile.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();expand();}};
      element.append(tile);const ctx=tile.querySelector('canvas').getContext('2d');this.feeds.push({id,ctx,image:ctx.createImageData(640,360)});
    }
    window.addEventListener('keydown',e=>{if(e.key==='Escape')view.expanded=null;});
  }
  draw(time) {
    const interval=1000/15;
    if(this.view.paused||document.hidden||time-this.last<interval)return;
    this.last=time-(time-this.last)%interval;
    const r=this.view.renderer;
    for(const feed of this.feeds) {
      r.setRenderTarget(this.target);r.render(this.view.scene,this.view.feedCameras[feed.id]);
      r.setRenderTarget(this.output);r.render(this.displayScene,this.displayCamera);
      r.readRenderTargetPixels(this.output,0,0,640,360,this.pixels);
      for(let y=0;y<360;y++)feed.image.data.set(this.pixels.subarray((359-y)*640*4,(360-y)*640*4),y*640*4);
      feed.ctx.putImageData(feed.image,0,0);
    }
    r.setRenderTarget(null);this.count++;
    if(time-this.started>1000){this.rate=this.count*1000/(time-this.started);this.count=0;this.started=time;}
  }
}
