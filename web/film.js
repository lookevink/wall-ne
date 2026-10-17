import * as THREE from 'three';
import {FleetScene} from './scene.js';
import {api} from './ui.js';

// Every frame is drawn from a server-computed state, so the same seed renders the same film.
const W=960,H=540,$=id=>document.getElementById(id);
const PHASES={night:'Night',dawn:'Dawn',sunrise:'Sunrise',morning:'Morning',midday:'Midday',afternoon:'Afternoon','golden hour':'Golden hour',dusk:'Dusk'};
const view=new FleetScene($('stage')),renderer=view.renderer;renderer.setPixelRatio(1);
const out=$('preview'),ctx=out.getContext('2d');
const camera=(fov,position,target)=>{const c=new THREE.PerspectiveCamera(fov,16/9,.05,700);c.layers.enable(1);c.position.set(...position);c.lookAt(...target);return c;};
const overview=camera(40,[24,15,33],[-3,0,11]);
// Looks along the front care row, past the docking lane and under no canopy.
const careRow=camera(46,[-7.5,2.7,17.6],[3.5,.3,13.6]);
const onboard=camera(70,[0,1.6,20],[0,1.4,10]);

function onboardCamera(state){
  // W3's arm camera during care stages; a follow camera while it drives or docks (its stowed arm blocks the chassis camera).
  const w=state.care_workers.W3,c=['inspection','irrigation','fertilizer','pests','extraction'].includes(w?.phase)&&w.camera;
  if(c){onboard.fov=c.fov;onboard.near=c.near||.05;onboard.far=60;onboard.position.set(...c.position);onboard.up.set(...c.up);onboard.lookAt(new THREE.Vector3(...c.position).add(new THREE.Vector3(...c.direction)));}
  else{const [x,z]=state.vehicles.W3.position;onboard.fov=60;onboard.near=.05;onboard.position.set(x+1.2,2.7,z+3.4);onboard.up.set(0,1,0);onboard.lookAt(x,.7,z-2.5);}
  onboard.updateProjectionMatrix();onboard.userData.label=c?'W3 ARM CAMERA':'W3 FOLLOW CAMERA';return onboard;
}
function render(cam){renderer.setRenderTarget(null);renderer.setSize(W,H,false);cam.aspect=16/9;cam.updateProjectionMatrix();renderer.render(view.scene,cam);return renderer.domElement;}
function pill(text,x,y,font,align='left',padX=12,height=30){
  ctx.font=font;const w=ctx.measureText(text).width+padX*2,left=align==='center'?x-w/2:x;
  ctx.fillStyle='rgba(16,18,18,.72)';ctx.beginPath();ctx.roundRect(left,y,w,height,height/2);ctx.fill();
  ctx.fillStyle='#fff4d8';ctx.textBaseline='middle';ctx.textAlign='left';ctx.fillText(text,left+padX,y+height/2+1);
}
function chart(x,y,w,h,title,series,key,max,min=0,bars=false,day){
  ctx.fillStyle='#8d806a';ctx.font='12px ui-monospace,Menlo,monospace';ctx.textAlign='left';ctx.fillText(title.toUpperCase(),x,y+10);
  const top=y+22,height=h-30,step=w/series.days;
  ctx.strokeStyle='#3a3a34';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,top+height+.5);ctx.lineTo(x+w,top+height+.5);ctx.stroke();
  const at=v=>top+height-(Math.min(max,Math.max(min,v))-min)/(max-min)*height;
  const points=series.values.map((s,i)=>[x+step*(i+.5),at(s[key]),s]);
  if(bars)for(const [px,py,s] of points){ctx.fillStyle=s.day===day?'#ed4235':'#a8957199';ctx.fillRect(px-step*.32,py,step*.64,top+height-py);}
  else{ctx.strokeStyle='#d8b56a';ctx.lineWidth=2.5;ctx.beginPath();points.forEach(([px,py],i)=>i?ctx.lineTo(px,py):ctx.moveTo(px,py));ctx.stroke();
    for(const [px,py,s] of points){ctx.fillStyle=s.day===day?'#ed4235':'#d8b56a';ctx.beginPath();ctx.arc(px,py,s.day===day?5:3,0,Math.PI*2);ctx.fill();}}
  const last=series.values.at(-1);if(last){ctx.fillStyle='#fff4d8';ctx.textAlign='right';ctx.font='14px ui-monospace,Menlo,monospace';ctx.fillText(String(last[key]),x+w,y+10);ctx.textAlign='left';}
}
function almanac(e,x0,y0){
  ctx.fillStyle='#1b1e1d';ctx.fillRect(x0,y0,W,H);
  ctx.textAlign='left';ctx.textBaseline='alphabetic';
  ctx.fillStyle='#e9a08f';ctx.font='600 15px ui-monospace,Menlo,monospace';ctx.fillText('ORCHARD ALMANAC',x0+40,y0+52);
  ctx.fillStyle='#fff4d8';ctx.textAlign='right';ctx.fillText(`DAY ${e.day} / ${e.days}`,x0+W-40,y0+52);ctx.textAlign='left';
  const hhmm=s=>`${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}`;
  ctx.fillStyle='#c3bba8';ctx.font='14px ui-monospace,Menlo,monospace';
  ctx.fillText(`${e.temperature.toFixed(0)}°C · ${e.humidity.toFixed(0)}% RH${e.mist>.15?' · mist':''}${e.weather.rain?` · ${e.weather.rain} mm rain`:''} · sunrise ${hhmm(e.sunrise)} · sunset ${hhmm(e.sunset)}`,x0+40,y0+80);
  ctx.fillStyle='#8d806a';ctx.font='12px ui-monospace,Menlo,monospace';
  for(const [text,dx] of [['TREE',0],['SOIL MOISTURE',52],['WEED',236],['PESTS',300]])ctx.fillText(text,x0+40+dx,y0+116);
  e.trees.forEach((t,i)=>{
    const y=y0+132+i*38,x=x0+40;
    ctx.fillStyle='#c3bba8';ctx.font='14px ui-monospace,Menlo,monospace';ctx.fillText(`R${t.row+1}`,x,y+16);
    ctx.fillStyle='#2c302e';ctx.fillRect(x+52,y+6,150,10);
    const wet=Math.min(1,t.moisture/70);ctx.fillStyle=t.moisture>=64?'#5f8fa0':'#a68b5b';ctx.fillRect(x+52,y+6,150*wet,10);
    ctx.fillStyle='#e9a08f';ctx.fillRect(x+52+150*Math.min(1,t.morning_moisture/70)-1,y+2,2,18);
    const r=6+(t.weed_size-.9)/.3*7,cx=x+250,cy=y+11;
    ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);
    if(t.weed_removed){ctx.strokeStyle='#557536';ctx.lineWidth=2;ctx.stroke();}else{ctx.fillStyle='#3f8f45';ctx.fill();}
    for(let p=0;p<4;p++){
      ctx.beginPath();ctx.arc(x+306+p*16,cy,5,0,Math.PI*2);
      if(p<t.pests_remaining){ctx.fillStyle='#9a6bb0';ctx.fill();}else if(p<t.pests){ctx.strokeStyle='#6b5a74';ctx.lineWidth=1.5;ctx.stroke();}
    }
    if(t.cared){ctx.fillStyle='#8fbf6a';ctx.font='600 16px ui-monospace,Menlo,monospace';ctx.fillText('✓',x+382,y+17);}
  });
  const series={days:e.days,values:e.series};
  chart(x0+470,y0+100,450,104,'Soil moisture at dawn %',series,'moisture',60,0,false,e.day);
  chart(x0+470,y0+204,450,104,'Caterpillars at dawn',series,'pests',30,0,true,e.day);
  chart(x0+470,y0+308,450,104,'Mean weed size',series,'weed_size',1.2,.9,false,e.day);
  chart(x0+470,y0+412,450,104,'Trees cared',series,'cared',10,0,true,e.day);
}
function draw(state){
  view.update(state);view.atmosphere.set(state.epoch);renderer.shadowMap.needsUpdate=true;
  const w3=onboardCamera(state);
  for(const [cam,x,y,label] of [[overview,0,0,'OVERVIEW'],[careRow,W,0,'CARE ROW'],[w3,0,H,w3.userData.label]]){
    ctx.drawImage(render(cam),x,y,W,H);pill(label,x+24,y+22,'600 14px ui-monospace,Menlo,monospace');
  }
  almanac(state.epoch,W,H);
  ctx.fillStyle='#0d0f0f';ctx.fillRect(W-1,0,2,2*H);ctx.fillRect(0,H-1,2*W,2);
  const e=state.epoch;pill(`Day ${e.day} · ${e.label} · ${PHASES[e.phase]||e.phase}`,W,H-30,'500 30px "Helvetica Neue",Arial,sans-serif','center',22,60);
}
function stamp(){const d=new Date(),p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}${p(d.getMonth()+1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;}

// Promise-driven, not timer-driven: rendering continues while the tab is in the background.
// ?reel=ID&from=N resumes an interrupted reel; frames are recomputed identically from the seed.
async function run(){
  $('render').disabled=true;const seed=Number($('seed').value),days=Number($('days').value),reel=query.get('reel')||stamp(),from=Number(query.get('from')||0),started=performance.now();
  try{
    const film=await api('/api/film/start',{seed,days,reel});
    for(let start=from;start<film.total;start+=10){
      const batch=await api('/api/film/frames',{reel,start,count:Math.min(10,film.total-start)});
      for(const [i,state] of batch.frames.entries()){
        draw(state);const index=start+i;
        await api('/api/timelapse/frame',{reel,index,data_url:out.toDataURL('image/jpeg',.9),meta:{day:state.epoch.day,clock:state.epoch.label}});
        const rate=(index+1-from)/((performance.now()-started)/1000);
        $('status').textContent=`Reel ${reel} · frame ${index+1}/${film.total} · day ${state.epoch.day} · ${rate.toFixed(1)} frames/s · ~${Math.ceil((film.total-index-1)/rate/60)} min left`;
      }
    }
    $('status').textContent=`Encoding ${film.total} frames…`;
    const result=await api('/api/timelapse/render',{reel,fps:30});
    $('status').textContent=`Saved ${result.seconds} s film: ${result.output}`;document.title='Done · Season film';
  }catch(error){$('status').textContent=`Stopped: ${error.message}`;}
  finally{$('render').disabled=false;}
}
const query=new URLSearchParams(location.search);
$('render').onclick=run;
if(query.has('seed'))$('seed').value=query.get('seed');if(query.has('days'))$('days').value=query.get('days');
// ?preview=N draws frame N without saving anything, for framing the cameras.
async function preview(index){await api('/api/film/start',{seed:Number($('seed').value),days:Number($('days').value)});const batch=await api('/api/film/frames',{start:index,count:1});draw(batch.frames[0]);$('status').textContent=`Preview of frame ${index}`;}
if(query.has('preview'))preview(Number(query.get('preview'))).catch(e=>{$('status').textContent=e.message;});
else if(query.get('autostart')==='1')run();
