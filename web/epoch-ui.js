import {$} from './ui.js';

const PHASES={night:'Night',dawn:'Dawn',sunrise:'Sunrise',morning:'Morning',midday:'Midday',afternoon:'Afternoon','golden hour':'Golden hour',dusk:'Dusk'};
const MODES={working:'Fleet working',paused:'Paused · clock held',settling:'Day’s work settled · to nightfall',night:'Night'};
const hhmm=seconds=>`${String(Math.floor(seconds/3600)%24).padStart(2,'0')}:${String(Math.floor(seconds%3600/60)).padStart(2,'0')}`;
function cell(text,className){const span=document.createElement('span');span.setAttribute('role','cell');span.textContent=text;if(className)span.className=className;return span;}

export function renderEpoch(epoch){
  if(!epoch)return;
  $('epoch-day').textContent=epoch.day?`DAY ${epoch.day}`:'PRE-SEASON';$('epoch-time').textContent=epoch.label;
  $('epoch-phase').textContent=PHASES[epoch.phase]||epoch.phase;
  $('epoch-weather').textContent=`${epoch.temperature.toFixed(0)}°C · ${epoch.humidity.toFixed(0)}% RH${epoch.mist>.15?' · mist':''}`;
  $('epoch-mode').textContent=!epoch.day?'Next day begins the season':epoch.mode==='night'&&epoch.auto_advance?'Night · next day soon':MODES[epoch.mode]||epoch.mode;
  // Sun (or moon) marker rides a daylight arc from sunrise to sunset.
  const t=Math.min(1,Math.max(0,(epoch.clock-epoch.sunrise)/(epoch.sunset-epoch.sunrise))),body=$('epoch-body'),up=epoch.sun.elevation>-3;
  body.setAttribute('cx',up?(4+56*t).toFixed(1):'32');body.setAttribute('cy',up?(32-28*Math.sin(Math.PI*t)).toFixed(1):'10');body.setAttribute('class',up?'sun':'moon');
  $('epoch').dataset.phase=up?'day':'night';
  if(document.activeElement!==$('day-minutes'))$('day-minutes').value=String(epoch.day_minutes);
  $('auto-advance').checked=epoch.auto_advance;
}

export function renderAlmanac(epoch){
  if(!epoch)return;
  const w=epoch.weather;
  $('almanac-weather').textContent=epoch.day?`Day ${epoch.day} · high ${w.high}°C, low ${w.low}°C · mean ${w.humidity}% RH · ${w.rain?w.rain+' mm overnight rain · ':''}sunrise ${hhmm(epoch.sunrise)}, sunset ${hhmm(epoch.sunset)}`:'Pre-season night. Next day begins day 1 with these morning conditions.';
  const head=document.createElement('div');head.className='almanac-row head';head.setAttribute('role','row');
  head.append(...['Tree','Soil moisture','Weed','Pests','Fertilizer','Today'].map(text=>cell(text)));
  const rows=epoch.trees.map(t=>{
    const row=document.createElement('div');row.className='almanac-row';row.setAttribute('role','row');
    const soil=cell('');soil.className='soil';const bar=document.createElement('i');bar.style.width=`${Math.min(100,t.moisture/70*100)}%`;
    const morning=document.createElement('b');morning.style.left=`${Math.min(100,t.morning_moisture/70*100)}%`;soil.append(bar,morning,document.createTextNode(`${t.moisture.toFixed(0)}%`));
    const status=t.cared?'✓ cared':t.weed_removed||t.pests_remaining<t.pests||t.moisture>t.morning_moisture+.5?'in progress':'—';
    row.append(cell(`R${t.row+1} · T${(t.column??12)+1}`),soil,cell(t.weed_removed?'pulled':`${t.weed_age?`${t.weed_age} d`:'seedling'} · ×${t.weed_size.toFixed(2)}`),
      cell(`${'●'.repeat(t.pests_remaining)}${'○'.repeat(Math.max(0,t.pests-t.pests_remaining))}`||'none','pests'),cell(t.prescription?`${t.prescription} g due`:'not due'),cell(status,t.cared?'pass':''));
    return row;
  });
  $('almanac').replaceChildren(head,...rows);
}

export function renderSeasonLog(epoch){
  if(!epoch)return;
  if(!epoch.history.length){const empty=document.createElement('p');empty.className='caption';empty.textContent='No completed days yet.';$('season-log').replaceChildren(empty);return;}
  $('season-log').replaceChildren(...epoch.history.slice().reverse().map(d=>{
    const row=document.createElement('div');row.className='event';
    for(const text of [`Day ${d.day}`,`${d.cared}/${d.tree_count??10} cared`,`${d.weeds_pulled} weeds · ${d.pests_removed} pests · ${d.water} L · ${d.fertilizer} g`,`${d.high}°C · ${d.humidity}% RH`]){const span=document.createElement('span');span.textContent=text;row.append(span);}
    return row;
  }));
}
