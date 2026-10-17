import * as THREE from 'three';

export class RoverViews {
  constructor(view,element) {
    this.view=view;this.element=element;this.feeds=[];this.last=0;this.rate=0;this.count=0;this.started=performance.now();
    this.masterCamera=view.camera.clone();
    // Reuse one HDR target and one display target across the camera rail.
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
    for(const id of [null,...Object.keys(view.feedCameras)]) {
      const master=id===null;
      const tile=document.createElement('button');tile.type='button';tile.className='feed';tile.setAttribute('aria-label',master?'Show master view':`Show ${id} first-person camera`);tile.setAttribute('aria-pressed',String(view.expanded===id));
      tile.innerHTML=`<canvas width="640" height="360" aria-hidden="true"></canvas><div class="feed-title"><b><i class="feed-indicator"></i>${master?'MASTER':id}</b><span>${master?'OVERVIEW':'FPV'}</span></div><div class="feed-state"><span data-feed-status>${master?'Master view':id==='R1'?'Recovery':id==='W5'?'Reserve':'Worker'}</span><small data-feed-battery>${master?'↗':'—'}</small></div>`;
      if(id==='WRIST'){tile.setAttribute('aria-label','Show W1 wrist decision camera');tile.querySelector('.feed-title span').textContent='DECISION RGB';}
      tile.onclick=()=>{view.expanded=id;};
      element.append(tile);const ctx=tile.querySelector('canvas').getContext('2d');this.feeds.push({id,tile,ctx,image:ctx.createImageData(640,360)});
    }
    document.getElementById('camera-count').textContent=String(this.feeds.length).padStart(2,'0');
    view.element.addEventListener('viewchange',()=>this.feeds.forEach(feed=>feed.tile.setAttribute('aria-pressed',String(view.expanded===feed.id))));
    window.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]'))view.expanded=null;});
  }
  update(state) {
    for(const feed of this.feeds){
      if(feed.id===null)continue;
      if(feed.id==='WRIST'){feed.tile.hidden=state.arena!=='orchard';feed.tile.querySelector('[data-feed-status]').textContent=state.phase||'Wrist';continue;}
      const vehicle=state.vehicles[feed.id];if(!vehicle)continue;
      feed.tile.querySelector('[data-feed-status]').textContent=vehicle.lifecycle==='spare'?'Reserve':vehicle.action?.kind||vehicle.lifecycle;
      feed.tile.querySelector('[data-feed-battery]').textContent=`${vehicle.battery.toFixed(0)}%`;
    }
  }
  resize() {
    const tile=this.feeds[0].tile,w=tile.clientWidth,h=tile.clientHeight;
    if(!w||!h)return;
    const scale=Math.min(devicePixelRatio,1.5,480/w,360/h),width=Math.max(1,Math.round(w*scale)),height=Math.max(1,Math.round(h*scale));
    if(this.target.width===width&&this.target.height===height)return;
    this.target.setSize(width,height);this.output.setSize(width,height);this.pixels=new Uint8Array(width*height*4);
    for(const feed of this.feeds){feed.ctx.canvas.width=width;feed.ctx.canvas.height=height;feed.image=feed.ctx.createImageData(width,height);feed.hasFrame=false;}
  }
  draw(time) {
    const interval=1000/15;
    if(this.view.paused||document.hidden||time-this.last<interval)return;
    this.last=time-(time-this.last)%interval;
    this.resize();const {width,height}=this.target;
    const r=this.view.renderer;
    const rail=this.element.getBoundingClientRect();
    for(const feed of this.feeds) {
      if(feed.tile.hidden)continue;
      const bounds=feed.tile.getBoundingClientRect();
      // Seed every tile once so pausing cameras never leaves an unseen tile blank.
      if(feed.hasFrame&&(bounds.bottom<=rail.top||bounds.top>=rail.bottom))continue;
      // A separate camera keeps the master preview from changing the main view's aspect.
      const camera=feed.id===null?this.masterCamera:this.view.feedCameras[feed.id];
      if(feed.id===null){camera.copy(this.view.camera);camera.fov=43;}
      camera.aspect=width/height;camera.updateProjectionMatrix();
      r.setRenderTarget(this.target);r.render(this.view.scene,camera);
      r.setRenderTarget(this.output);r.render(this.displayScene,this.displayCamera);
      r.readRenderTargetPixels(this.output,0,0,width,height,this.pixels);
      for(let y=0;y<height;y++)feed.image.data.set(this.pixels.subarray((height-1-y)*width*4,(height-y)*width*4),y*width*4);
      feed.ctx.putImageData(feed.image,0,0);
      feed.hasFrame=true;
    }
    r.setRenderTarget(null);this.count++;
    if(time-this.started>1000){this.rate=this.count*1000/(time-this.started);this.count=0;this.started=time;}
  }
}
