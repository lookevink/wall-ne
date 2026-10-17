import {FleetScene} from './scene.js';
import {RoverViews} from './rover-views.js';
import {$,api,notice,checks,journal,button,download} from './ui.js';
let view,feeds,state,currentSession=null,lastFrame=null,lastDepth=null;
const workerFrames=new Map(),workerDepths=new Map(),workerScenes=new Map();
const decisionCanvas=document.createElement('canvas');decisionCanvas.width=640;decisionCanvas.height=360;
try{view=new FleetScene($('viewport'));feeds=new RoverViews(view,$('feeds'));}catch(e){notice(`Renderer unavailable: ${e.message}`);}
button('reset',()=>api('/api/reset',{mission:$('mission').value,seed:Number($('seed').value),mode:$('mode').value,speed:Number($('speed').value)}));
for(const action of ['start','pause','breakdown','false-claim','retry','abort'])button(action,()=>api(`/api/${action}`,{}));
button('export',()=>download(state,`wall-ne-${state.id}.json`));
button('camera-pause',()=>{view.paused=!view.paused;$('camera-pause').textContent=view.paused?'Resume cameras':'Pause cameras';});
button('wind',()=>{view.windEnabled=!view.windEnabled;$('wind').textContent=`Wind ${view.windEnabled?'on':'off'}`;});
$('wind').textContent=`Wind ${view?.windEnabled?'on':'off'}`;
$('mission').onchange=()=>{$('mode').disabled=$('mission').value!=='watering';};$('mission').onchange();
const workerFaults=document.createElement('div');workerFaults.className='small-buttons';workerFaults.setAttribute('aria-label','Individual worker breakdowns');
for(const id of ['W1','W2','W3','W4','W5']){const control=document.createElement('button');control.textContent=`Break ${id}`;control.dataset.breakdownWorker=id;control.disabled=true;control.onclick=()=>api('/api/breakdown',{robots:[id]}).catch(error=>notice(error.message));workerFaults.append(control);}
$('breakdown').parentElement.after(workerFaults);

function updateFleet(vehicles){
  for(const v of vehicles){
    // Keep buttons mounted so telemetry refreshes do not steal keyboard focus.
    let row=$('robots').querySelector(`[data-robot="${v.id}"]`);
    if(!row){
      row=document.createElement('button');row.type='button';row.className='robot-row';row.dataset.robot=v.id;row.setAttribute('aria-label',`Ride along with ${v.id}`);
      row.innerHTML='<span class="robot-symbol"></span><span><span class="robot-name"></span><span class="robot-detail"></span></span><span class="battery"><span class="battery-value"></span><span class="bar"><i></i></span></span>';
      row.querySelector('.robot-symbol').textContent=v.id;
      row.onclick=()=>{view.expanded=v.id;$('mission-dialog').close();};$('robots').append(row);
    }
    row.querySelector('.robot-name').textContent=v.role==='retriever'?'Recovery unit':v.lifecycle==='spare'?'Reserve worker':'Orchard worker';
    row.querySelector('.battery-value').textContent=`${v.battery.toFixed(0)}%`;row.querySelector('.bar i').style.width=`${v.battery}%`;
    const telemetry=state.telemetry[v.id],age=telemetry?Math.max(0,(Date.now()-Date.parse(telemetry.wall_utc))/1000):null;
    row.querySelector('.robot-detail').textContent=`${v.lifecycle} · ${v.action?.kind||'standby'} · ${v.water.toFixed(0)} water${telemetry?(state.status==='running'?` · heartbeat ${age.toFixed(1)}s${age>5?' (stale)':''} · ${telemetry.waiting_reason||'no wait'} · progress r${telemetry.last_progress_revision}${telemetry.fault?' · '+telemetry.fault:''}`:` · ${state.status}`):''}`;
  }
}
async function poll(){
  try{
    state=await api('/api/state');if(['Failed to fetch','stale capture request','stale or superseded scan frame'].includes($('notice').textContent))notice('');view?.update(state);feeds?.update(state);
    $('status').textContent=state.status.replaceAll('_',' ');$('status').classList.toggle('error',['failed','blocked','storage_blocked'].includes(state.status));
    const arm=state.arena==='orchard',care=['full_care','fleet_care'].includes(state.mission_type),fleetCare=state.mission_type==='fleet_care',vehicles=Object.values(state.vehicles);
    if(currentSession!==state.id){currentSession=state.id;lastFrame=null;lastDepth=null;$('mission').value=care?'full_care':arm?'weeding':'watering';$('mission').onchange();$('seed').value=state.seed;}
    $('goal').textContent=state.contract.goal||'Inspect and water the orchard, preserve reserve and return.';
    $('inspected-label').textContent=care?'Trees cared for':arm?'Extracted':'Inspected';$('watered-label').textContent=care?'Collected':arm?'Collected':'Watered';$('inspected-total').textContent=care?`/ ${state.tasks.length}`:arm?'/ 1':'/ 36';
    if(care){$('inspected').textContent=fleetCare?Object.values(state.assignments).filter(a=>a.status==='completed').length:state.completed_trees.length;$('watered').textContent=fleetCare?Object.values(state.care_workers).reduce((n,w)=>n+w.collected_total,0)+Object.entries(state.results).filter(([id])=>!Object.values(state.care_workers).some(w=>w.id===id)).length:state.collected_total;$('critical-total').textContent=`/ ${state.tasks.length}`;}
    else if(arm){$('inspected').textContent=Number(state.extracted);$('watered').textContent=Number(state.deposited);$('critical-total').textContent='/ 1';}
    else{const zones=Object.values(state.zones),critical=zones.filter(z=>z.initial<=state.contract.critical);$('inspected').textContent=zones.filter(z=>z.inspected_at!==null).length;$('watered').textContent=critical.filter(z=>z.moisture>=65-1e-6).length;$('critical-total').textContent=`/ ${critical.length}`;}
    $('arm-feedback').hidden=!arm;$('arm-feedback').textContent=fleetCare?`${state.feedback} · ${Object.values(state.care_workers).filter(w=>w.status==='running').length} workers active${state.navigation_owner?' · lane reserved for '+state.navigation_owner:''}`:arm?`W1 · ${state.phase} · ${state.status==='completed'?(care?'All trees fully cared for and rover returned':'Extraction, collection and return verified'):state.feedback} · ${state.load.toFixed(1)} N load`:'';
    $('breakdown').disabled=$('false-claim').disabled=arm;
    $('clock').textContent=`${String(Math.floor(state.time/60)).padStart(2,'0')}:${String(Math.floor(state.time%60)).padStart(2,'0')}`;$('minimum').textContent=Math.min(...vehicles.map(v=>v.minimum_battery)).toFixed(1);
    checks(state.checks);journal(state.events);updateFleet(vehicles);
    for(const control of workerFaults.children)control.disabled=arm||state.status!=='running'||state.vehicles[control.dataset.breakdownWorker]?.lifecycle==='disabled';
    $('storage').textContent=state.storage.error||`Supabase · committed event ${state.storage.committed_sequence}`;
    $('inference').textContent=`${arm?`W1 wrist / ${state.provider_routes?.treatment?.fallback?'Gateway fallback':'Crusoe'}`:state.config.mode==='demo'?'Rule-based demo':'Live roles'} · ${state.inference.calls} calls · ${state.inference.tokens} tokens · ${state.inference.cost===null?'cost unknown':'$'+state.inference.cost.toFixed(4)}`;
    if(state.storage.error)notice(state.storage.error);
    if(fleetCare&&view&&state.status==='running'){
      for(const [worker,w] of Object.entries(state.care_workers)){
        if(w.status!=='running')continue;
        const req=w.frame_request;
        if(req&&workerFrames.get(worker)!==req.id){const data=view.armControl.capture(req.camera,decisionCanvas);const frame=await api('/api/frame',{arena:'orchard',worker,mission_id:w.id,request_id:req.id,data_url:data});workerFrames.set(worker,req.id);workerScenes.set(worker,{frameId:frame.id,state});}
        const depth=w.depth_request;
        if(depth&&workerDepths.get(worker)!==depth.id){
          const captured=workerScenes.get(worker);if(!captured||captured.frameId!==depth.frame_id)throw new Error('Reload lost the captured fleet scene; pause and resume for fresh observations');
          let points;try{view.update(captured.state);points=view.armControl.depth(depth);}finally{view.update(state);}
          await api('/api/depth',{arena:'orchard',worker,mission_id:w.id,request_id:depth.id,frame_id:depth.frame_id,revision:depth.revision,points});workerDepths.set(worker,depth.id);
        }
      }
    }else if(arm&&view&&state.status==='running'){
      const req=state.frame_request;
      if(req&&lastFrame!==req.id){const data=view.armControl.capture(req.camera,decisionCanvas);await api('/api/frame',{arena:'orchard',mission_id:state.id,request_id:req.id,data_url:data});lastFrame=req.id;}
      const depth=state.depth_request;
      if(depth&&lastDepth!==depth.id){await api('/api/depth',{arena:'orchard',mission_id:state.id,request_id:depth.id,frame_id:depth.frame_id,revision:depth.revision,points:view.armControl.depth(depth)});lastDepth=depth.id;}
    }
  }catch(e){notice(e.message);}
  setTimeout(poll,650);
}
poll();
function animate(time){
  requestAnimationFrame(animate);if(!view)return;
  const start=performance.now();feeds?.draw(time);const drawn=view.draw(time);if(drawn)view.lastCpu=performance.now()-start;
  if(time%1000<40)$('performance').textContent=`${view.fps.toFixed(1)} overview fps · ${(feeds?.rate||0).toFixed(1)} feed fps · ${view.renderer.info.render.calls} draw calls · ${view.renderer.info.memory.geometries} geometries · ${(view.lastCpu||0).toFixed(1)} ms CPU submission/readback · ${view.element.clientWidth}×${view.element.clientHeight} · DPR ${view.renderer.getPixelRatio()} · ${view.backend}`;
}
requestAnimationFrame(animate);
