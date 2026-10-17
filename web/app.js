import {FleetScene} from './scene.js';
import {RoverViews} from './rover-views.js';
import {$,api,notice,checks,journal,button,download} from './ui.js';
let view,feeds,state;
try{view=new FleetScene($('viewport'));feeds=new RoverViews(view,$('feeds'));}catch(e){notice(`Renderer unavailable: ${e.message}`);}
button('reset',()=>api('/api/reset',{seed:Number($('seed').value),mode:$('mode').value,speed:Number($('speed').value)}));
for(const action of ['start','pause','breakdown','false-claim','retry','abort'])button(action,()=>api(`/api/${action}`,{}));
button('export',()=>download(state,`wall-ne-${state.id}.json`));
button('camera-pause',()=>{view.paused=!view.paused;$('camera-pause').textContent=view.paused?'Resume cameras':'Pause cameras';});
button('wind',()=>{view.windEnabled=!view.windEnabled;$('wind').textContent=`Wind ${view.windEnabled?'on':'off'}`;});
$('wind').textContent=`Wind ${view?.windEnabled?'on':'off'}`;
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
    row.querySelector('.robot-detail').textContent=`${v.lifecycle} · ${v.action?.kind||'standby'} · ${v.water.toFixed(0)} water${telemetry?` · heartbeat ${age.toFixed(1)}s${age>5?' (stale)':''} · ${telemetry.waiting_reason||'no wait'} · progress r${telemetry.last_progress_revision}${telemetry.fault?' · '+telemetry.fault:''}`:''}`;
  }
}
async function poll(){
  try{
    state=await api('/api/state');if($('notice').textContent==='Failed to fetch')notice('');view?.update(state);feeds?.update(state);
    $('status').textContent=state.status.replaceAll('_',' ');$('status').classList.toggle('error',['failed','blocked','storage_blocked'].includes(state.status));
    const zones=Object.values(state.zones),vehicles=Object.values(state.vehicles),critical=zones.filter(z=>z.initial<=state.contract.critical);
    $('inspected').textContent=zones.filter(z=>z.inspected_at!==null).length;$('watered').textContent=critical.filter(z=>z.moisture>=65-1e-6).length;$('critical-total').textContent=`/ ${critical.length}`;
    $('clock').textContent=`${String(Math.floor(state.time/60)).padStart(2,'0')}:${String(Math.floor(state.time%60)).padStart(2,'0')}`;$('minimum').textContent=Math.min(...vehicles.map(v=>v.minimum_battery)).toFixed(1);
    checks(state.checks);journal(state.events);updateFleet(vehicles);
    for(const control of workerFaults.children)control.disabled=state.status!=='running'||state.vehicles[control.dataset.breakdownWorker]?.lifecycle==='disabled';
    $('storage').textContent=state.storage.error||`Supabase · committed event ${state.storage.committed_sequence}`;
    $('inference').textContent=`${state.config.mode==='demo'?'Rule-based demo':'Live roles'} · ${state.inference.calls} calls · ${state.inference.tokens} tokens · ${state.inference.cost===null?'cost unknown':'$'+state.inference.cost.toFixed(4)}`;
    if(state.storage.error)notice(state.storage.error);
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
