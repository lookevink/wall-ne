import {api} from './ui.js';

// Overview timelapse: one 1080p frame per interval, saved by the local server.
// Frames are cropped to fill 16:9 so a resized window never changes the reel size.
export class Timelapse {
  constructor(){
    this.reel=null;this.lastReel=null;this.interval=2000;this.caption=true;this.last=0;this.busy=false;this.index=0;this.frames=0;this.error=null;
    this.canvas=document.createElement('canvas');this.canvas.width=1920;this.canvas.height=1080;this.ctx=this.canvas.getContext('2d');
  }
  get recording(){return Boolean(this.reel);}
  start(interval,caption){
    const d=new Date(),p=n=>String(n).padStart(2,'0');
    this.reel=`${d.getFullYear()}${p(d.getMonth()+1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
    Object.assign(this,{interval,caption,index:0,frames:0,last:0,error:null});
  }
  stop(){this.lastReel=this.reel||this.lastReel;this.reel=null;return this.lastReel;}
  due(time){return this.recording&&!this.busy&&time-this.last>=this.interval;}
  // Call right after the overview renders, while its drawing buffer holds that frame.
  grab(source,time,title,subtitle,meta){
    this.last=time;const {canvas,ctx}=this,scale=Math.max(canvas.width/source.width,canvas.height/source.height),w=source.width*scale,h=source.height*scale;
    ctx.drawImage(source,(canvas.width-w)/2,(canvas.height-h)/2,w,h);
    if(this.caption&&title){
      const shade=ctx.createLinearGradient(0,canvas.height-220,0,canvas.height);shade.addColorStop(0,'rgba(10,14,14,0)');shade.addColorStop(1,'rgba(10,14,14,.55)');
      ctx.fillStyle=shade;ctx.fillRect(0,canvas.height-220,canvas.width,220);
      ctx.fillStyle='#fff4d8';ctx.font='500 64px "Helvetica Neue",Arial,sans-serif';ctx.textBaseline='alphabetic';ctx.fillText(title,72,canvas.height-104);
      ctx.fillStyle='#e9d8b8';ctx.font='26px ui-monospace,Menlo,monospace';ctx.fillText(subtitle||'',74,canvas.height-60);
    }
    const reel=this.reel,index=this.index++;this.busy=true;
    canvas.toBlob(blob=>{
      if(!blob){this.busy=false;return;}
      const reader=new FileReader();
      reader.onload=()=>api('/api/timelapse/frame',{reel,index,data_url:reader.result,meta}).then(r=>{if(r.reel===this.reel)this.frames=r.frames;this.error=null;}).catch(e=>{this.error=e.message;}).finally(()=>{this.busy=false;});
      reader.onerror=()=>{this.busy=false;};reader.readAsDataURL(blob);
    },'image/jpeg',.9);
  }
  render(fps=30){if(!this.lastReel)throw new Error('Record a reel first');return api('/api/timelapse/render',{reel:this.lastReel,fps});}
}
