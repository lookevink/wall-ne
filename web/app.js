import {FleetScene} from './scene.js';
import {RoverViews} from './rover-views.js';
import {$,api,notice,checks,journal,button,download} from './ui.js';
import {renderEpoch,renderAlmanac,renderSeasonLog} from './epoch-ui.js';
import {Timelapse} from './timelapse.js';
let view,feeds,state,currentSession=null,lastFrame=null,lastDepth=null;
const recorder=new Timelapse();
const workerFrames=new Map(),workerDepths=new Map(),workerScenes=new Map();
const decisionCanvas=document.createElement('canvas');decisionCanvas.width=640;decisionCanvas.height=360;
try{view=new FleetScene($('viewport'));feeds=new RoverViews(view,$('feeds'));}catch(e){notice(`Renderer unavailable: ${e.message}`);}
// Agents are always on: a new day or season starts its mission immediately; Pause holds the mission and the clock.
const plan=()=>({mission:$('mission').value,mode:$('mode').value,speed:Number($('speed').value),care_controller:$('care-controller').value});
button('next-day',()=>api('/api/next-day',plan()));
button('new-season',()=>api('/api/season',{...plan(),seed:Number($('seed').value)}).then(()=>$('orchard-menu').close()));
button('pause',()=>api(state?.status==='running'?'/api/pause':'/api/start',{}));
$('day-minutes').onchange=()=>api('/api/epoch',{day_minutes:Number($('day-minutes').value)}).catch(e=>notice(e.message));
$('auto-advance').onchange=()=>api('/api/epoch',{auto_advance:$('auto-advance').checked}).catch(e=>notice(e.message));
button('tl-record',()=>{
  if(recorder.recording)recorder.stop();else recorder.start(Number($('tl-interval').value),$('tl-caption').checked);
  $('tl-record').textContent=recorder.recording?'■ Stop recording':'● Record timelapse';$('tl-render').disabled=recorder.recording||!recorder.lastReel;
});
button('tl-render',async()=>{$('tl-status').textContent=`Rendering reel ${recorder.lastReel}…`;const r=await recorder.render(30);$('tl-status').textContent=`Saved ${r.seconds} s video (${r.frames} frames at ${r.fps} fps): ${r.output}`;});
for(const action of ['breakdown','false-claim','retry','abort'])button(action,()=>api(`/api/${action}`,{}));
button('export',()=>download(state,`wall-ne-${state.id}.json`));
button('camera-pause',()=>{view.paused=!view.paused;$('camera-pause').textContent=view.paused?'Resume cameras':'Pause cameras';});
button('wind',()=>{view.windEnabled=!view.windEnabled;$('wind').textContent=`Wind ${view.windEnabled?'on':'off'}`;});
$('wind').textContent=`Wind ${view?.windEnabled?'on':'off'}`;
$('mission').onchange=()=>{$('mode').disabled=$('mission').value!=='watering';$('care-controller').disabled=$('mission').value!=='full_care';};$('mission').onchange();
const workerFaults=document.createElement('div');workerFaults.className='small-buttons';workerFaults.setAttribute('aria-label','Individual worker breakdowns');
for(const id of ['W1','W2','W3','W4','W5']){const control=document.createElement('button');control.textContent=`Break ${id}`;control.dataset.breakdownWorker=id;control.disabled=true;control.onclick=()=>api('/api/breakdown',{robots:[id]}).catch(error=>notice(error.message));workerFaults.append(control);}
$('breakdown').parentElement.after(workerFaults);
$('hud-close').onclick=()=>{if(view)view.expanded=null;};
view?.element.addEventListener('viewchange',()=>{if(state)updateHud(state);});

const HUD_EVENTS=new Set(['accepted','rejected','completed','cancelled','breakdown','recovered','contact','slip','extraction','deposit','dropped','incident','incident_resolved','incident_response','decision','inference_error','provider_fallback','telemetry_query','escalation','worker_dispatched','worker_finished','inspection']);
const ALERT_EVENTS=new Set(['rejected','breakdown','slip','dropped','incident','inference_error','escalation','cancelled']);
function describe(e){
  const p=e.payload||{};
  switch(e.type){
    case 'accepted':case 'rejected':return `${p.receipt?.action||''}${p.receipt?.reason?' · '+p.receipt.reason:''}`;
    case 'decision':{const d=p.result?.decision;return d?`${d.action}${d.rationale?' · '+d.rationale.slice(0,110):''}`:'';}
    case 'incident':return `${p.incident_kind} · ${p.detail||''}`;
    case 'incident_resolved':return `${p.incident_kind} · ${p.response?p.response.decision:'resolved'}`;
    case 'incident_response':return `${p.incident_kind} on ${p.target} → ${p.decision} · ${p.reason||''}`;
    case 'slip':return `force ${p.force} N at lift ${Number(p.lift||0).toFixed(2)} m`;
    case 'contact':return `load ${p.load} N at ${p.force} N`;
    case 'completed':return p.action||p.result?.kind||'';
    case 'cancelled':return p.reason||'';
    case 'inspection':return `zone ${p.zone} · moisture ${Number(p.moisture).toFixed(0)}%`;
    case 'telemetry_query':return `${p.arguments?.robot} since ${p.arguments?.since_sim_time}s · ${p.returned} of ${p.samples} heartbeats`;
    default:return Object.entries(p).filter(([,v])=>['string','number','boolean'].includes(typeof v)).slice(0,3).map(([k,v])=>`${k} ${v}`).join(' · ');
  }
}
// Everything here is read from the authoritative snapshot: health is code-computed, decisions are the model's own words.
function updateHud(state){
  const id=view?.expanded,hud=$('worker-hud'),worker=state.care_workers?.[id],v=worker?.robot||(id&&state.vehicles?.[id]);
  state=worker||state;
  if(!v){hud.hidden=true;return;}
  const t=state.telemetry?.[id],h=state.health?.[id];hud.hidden=false;
  $('hud-id').textContent=id;$('hud-role').textContent=v.role==='retriever'?'Recovery unit':v.lifecycle==='spare'?'Reserve worker':'Orchard worker';
  const status=h?.status||(v.lifecycle==='disabled'?'disabled':'healthy');$('hud-health').textContent=status.replaceAll('_',' ');$('hud-health').dataset.status=status;
  $('hud-state').textContent=`${worker?.status||v.lifecycle} · ${v.action?.kind||worker?.waiting||'standby'}${v.action?.stage?' · '+v.action.stage:''}`;
  $('hud-task').textContent=v.action?.zone||v.action?.target||t?.task_id||(state.arena==='orchard'&&state.phase?state.phase:'—');
  $('hud-battery').textContent=`${v.battery.toFixed(1)}% · min ${Number(v.minimum_battery??v.battery).toFixed(1)}%`;$('hud-water').textContent=v.water==null?'—':`${v.water.toFixed(1)} L`;
  $('hud-heartbeat').textContent=h?`${h.heartbeat_age.toFixed(1)} s · ${h.waiting_reason||'no wait'}`:'—';
  $('hud-progress').textContent=t?`r${t.last_progress_revision} · ${Math.max(0,state.time-(t.last_progress_sim_time??state.time)).toFixed(1)} s ago`:'—';
  $('hud-fault').textContent=v.fault||h?.fault||'none';
  const arm=!!t&&Array.isArray(t.joints);$('hud-arm').hidden=!arm;
  if(arm){
    const bars=$('hud-joints');
    if(bars.children.length!==t.joints.length)bars.replaceChildren(...t.joints.map(()=>{const s=document.createElement('span');s.innerHTML='<i><b></b></i><small></small>';return s;}));
    t.joints.forEach((q,i)=>{const s=bars.children[i];s.querySelector('b').style.width=`${(q+180)/3.6}%`;s.querySelector('small').textContent=q.toFixed(0);});
    const p=t.tool_pose?.position||[];
    $('hud-tool').textContent=`tool ${p.map(x=>x.toFixed(2)).join(' / ')} m · jaw ${(t.opening*100).toFixed(1)} cm · ${t.force} N cmd · ${Number(t.load||0).toFixed(1)} N load · ${t.holding?'holding':'empty'}${t.extracted?' · extracted':''}${t.deposited?' · collected':''}`;
  }
  const mine=(state.robot_events?.[id]||state.events.filter(e=>e.robot_id===id)).filter(e=>HUD_EVENTS.has(e.type));
  const decision=[...mine].reverse().find(e=>e.type==='decision');$('hud-decision').textContent=decision?describe(decision):state.config.mode==='demo'?'rule-based demo: no model decisions':'no model decision yet';
  $('hud-events').replaceChildren(...mine.slice(-8).reverse().map(e=>{const li=document.createElement('li');if(ALERT_EVENTS.has(e.type))li.className='alert';li.innerHTML='<b></b><span></span>';li.querySelector('b').textContent=`${Number(e.sim_time).toFixed(1)}s ${e.type.replaceAll('_',' ')}`;li.querySelector('span').textContent=describe(e);return li;}));
}
function updateIncidents(state){
  const strip=$('incident-strip'),open=state.incidents?.open||[];
  if(!open.length&&!state.escalation){strip.hidden=true;return;}
  strip.hidden=false;
  strip.replaceChildren(...open.map(i=>{const d=document.createElement('div');d.innerHTML='<b></b> <span></span>';d.querySelector('b').textContent=`INCIDENT · ${i.kind.replaceAll('_',' ')} · ${i.robot}`;d.querySelector('span').textContent=`${i.detail}${i.response?` → orchestrator: ${i.response.decision} (${i.response.reason})`:state.config.mode==='live'?' → orchestrator engaged':' → rule-based recovery'}`;return d;}));
  if(state.escalation){const d=document.createElement('div');d.innerHTML='<b>ESCALATED · HUMAN NEEDED</b> <span></span>';d.querySelector('span').textContent=`${state.escalation.robot}: ${state.escalation.reason} · resume when handled`;strip.prepend(d);}
}

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
const sensorPending=new Set();
async function poll(){
  try{
    state=await api('/api/state');if(['Failed to fetch','stale capture request','stale or superseded scan frame'].includes($('notice').textContent))notice('');view?.update(state);feeds?.update(state);
    $('status').textContent=state.status.replaceAll('_',' ');$('status').classList.toggle('error',['failed','blocked','storage_blocked'].includes(state.status));
    const arm=state.arena==='orchard',care=['full_care','fleet_care'].includes(state.mission_type),fleetCare=state.mission_type==='fleet_care',vehicles=Object.values(state.vehicles);
    if(currentSession!==state.id){currentSession=state.id;lastFrame=null;lastDepth=null;const p=state.epoch?.plan;$('mission').value=p?.mission||(care?'full_care':arm?'weeding':'watering');if(p){$('mode').value=p.mode;$('speed').value=String(p.speed);}$('care-controller').value=state.config.care_controller||'standard';$('mission').onchange();$('seed').value=state.epoch?.seed??state.seed;}
    renderEpoch(state.epoch);renderAlmanac(state.epoch);renderSeasonLog(state.epoch);
    if(state.epoch?.notice)notice(state.epoch.notice);
    const terminal=['completed','failed','blocked','aborted'].includes(state.status);
    $('pause').textContent=state.status==='running'?'Pause':'Resume';$('pause').disabled=!state.epoch?.day||terminal;
    $('next-day').textContent=state.epoch?.day?'Next day ⏭':'Begin day 1 ⏭';
    $('rec-badge').hidden=!recorder.recording;
    if(recorder.recording)$('tl-status').textContent=`Recording reel ${recorder.reel} · ${recorder.frames} frames saved${recorder.error?` · last upload failed: ${recorder.error}`:''}`;
    $('goal').textContent=state.contract.goal||'Inspect and water the orchard, preserve reserve and return.';
    $('inspected-label').textContent=care?'Trees cared for':arm?'Extracted':'Inspected';$('watered-label').textContent=care?'Collected':arm?'Collected':'Watered';$('inspected-total').textContent=care?`/ ${state.tasks.length}`:arm?'/ 1':'/ 36';
    if(care){$('inspected').textContent=fleetCare?Object.values(state.assignments).filter(a=>a.status==='completed').length:state.completed_trees.length;$('watered').textContent=fleetCare?Object.values(state.care_workers).reduce((n,w)=>n+w.collected_total,0)+Object.entries(state.results).filter(([id])=>!Object.values(state.care_workers).some(w=>w.id===id)).length:state.collected_total;$('critical-total').textContent=`/ ${state.tasks.length}`;}
    else if(arm){$('inspected').textContent=Number(state.extracted);$('watered').textContent=Number(state.deposited);$('critical-total').textContent='/ 1';}
    else{const zones=Object.values(state.zones),critical=zones.filter(z=>z.initial<=state.contract.critical);$('inspected').textContent=zones.filter(z=>z.inspected_at!==null).length;$('watered').textContent=critical.filter(z=>z.moisture>=65-1e-6).length;$('critical-total').textContent=`/ ${critical.length}`;}
    $('arm-feedback').hidden=!arm;$('arm-feedback').textContent=fleetCare?`${state.feedback} · ${Object.values(state.care_workers).filter(w=>w.status==='running').length} workers active${state.navigation_owner?' · lane reserved for '+state.navigation_owner:''}`:arm?`W1 · ${state.phase} · ${state.status==='completed'?(care?'All trees fully cared for and rover returned':'Extraction, collection and return verified'):state.feedback} · ${state.load.toFixed(1)} N load`:'';
    $('breakdown').disabled=$('false-claim').disabled=arm;
    $('clock').textContent=`${String(Math.floor(state.time/60)).padStart(2,'0')}:${String(Math.floor(state.time%60)).padStart(2,'0')}`;$('minimum').textContent=Math.min(...vehicles.map(v=>v.minimum_battery)).toFixed(1);
    checks(state.checks);journal(state.events);updateFleet(vehicles);updateHud(state);updateIncidents(state);
    for(const control of workerFaults.children)control.disabled=arm||state.status!=='running'||state.vehicles[control.dataset.breakdownWorker]?.lifecycle==='disabled';
    $('storage').textContent=state.storage.error||(Object.keys(state.background_sync?.recovery_errors||{}).length?'Local evidence recovery needs attention':state.background_sync?.pending_operations?`Evidence saved locally · ${state.background_sync.pending_operations} background sync operations${Object.values(state.background_sync.sessions).some(s=>s.error)?' · retrying':''}`:`Supabase · synced event ${state.storage.committed_sequence}`);
    $('inference').textContent=`${arm?`W1 wrist / ${state.provider_routes?.treatment?.fallback?'Gateway fallback':'Crusoe'}`:state.config.mode==='demo'?'Rule-based demo':'Live roles'} · ${state.inference.calls} calls · ${state.inference.tokens} tokens · ${state.inference.cost===null?'cost unknown':'$'+state.inference.cost.toFixed(4)}`;
    if(state.storage.error)notice(state.storage.error);
    if(fleetCare&&view&&state.status==='running'){
      const deliveries=[];
      const deliver=(key,promise)=>{
        sensorPending.add(key);
        deliveries.push(promise.catch(e=>notice(e.message)).finally(()=>sensorPending.delete(key)));
      };
      for(const [worker,w] of Object.entries(state.care_workers)){
        if(w.status!=='running')continue;
        const req=w.frame_request;
        if(req&&workerFrames.get(worker)!==req.id&&!sensorPending.has(req.id)){const scene=state,data=view.armControl.capture(req.camera,decisionCanvas);deliver(req.id,api('/api/frame',{arena:'orchard',worker,mission_id:w.id,request_id:req.id,data_url:data}).then(frame=>{workerFrames.set(worker,req.id);workerScenes.set(worker,{frameId:frame.id,state:scene});}));}
        const depth=w.depth_request;
        if(depth&&workerDepths.get(worker)!==depth.id&&!sensorPending.has(depth.id)){
          const captured=workerScenes.get(worker);if(!captured||captured.frameId!==depth.frame_id)throw new Error('Reload lost the captured fleet scene; pause and resume for fresh observations');
          let points;try{view.update(captured.state);points=view.armControl.depth(depth);}finally{view.update(state);}
          deliver(depth.id,api('/api/depth',{arena:'orchard',worker,mission_id:w.id,request_id:depth.id,frame_id:depth.frame_id,revision:depth.revision,points}).then(()=>workerDepths.set(worker,depth.id)));
        }
      }
      if(state.config.care_controller!=='ultra_fast')await Promise.allSettled(deliveries);
    }else if(arm&&view&&state.status==='running'){
      const req=state.frame_request;
      if(req&&lastFrame!==req.id){const data=view.armControl.capture(req.camera,decisionCanvas);await api('/api/frame',{arena:'orchard',mission_id:state.id,request_id:req.id,data_url:data});lastFrame=req.id;}
      const depth=state.depth_request;
      if(depth&&lastDepth!==depth.id){await api('/api/depth',{arena:'orchard',mission_id:state.id,request_id:depth.id,frame_id:depth.frame_id,revision:depth.revision,points:view.armControl.depth(depth)});lastDepth=depth.id;}
    }
  }catch(e){notice(e.message);}
  setTimeout(poll,state?.config?.care_controller==='ultra_fast'?100:650);
}
poll();
function animate(time){
  requestAnimationFrame(animate);if(!view)return;
  view.atmosphere.tick(time);
  const start=performance.now();feeds?.draw(time);const drawn=view.draw(time);if(drawn)view.lastCpu=performance.now()-start;
  if(drawn&&state&&recorder.due(time)){
    const e=state.epoch||{},done=state.mission_type==='fleet_care'?Object.values(state.assignments).filter(a=>a.status==='completed').length:null;
    recorder.grab(view.renderer.domElement,time,e.day?`Day ${e.day} · ${e.label}`:`Pre-season · ${e.label||''}`,
      `WALL-NE ORCHARD · ${(e.phase||'').toUpperCase()}${done===null?'':` · ${done}/${state.tasks.length} TREES CARED`}`,{day:e.day,clock:e.label,session_id:state.id});
  }
  if(time%1000<40)$('performance').textContent=`${view.fps.toFixed(1)} overview fps · ${(feeds?.rate||0).toFixed(1)} feed fps · ${view.renderer.info.render.calls} draw calls · ${view.renderer.info.memory.geometries} geometries · ${(view.lastCpu||0).toFixed(1)} ms CPU submission/readback · ${view.element.clientWidth}×${view.element.clientHeight} · DPR ${view.renderer.getPixelRatio()} · ${view.backend}`;
}
requestAnimationFrame(animate);
