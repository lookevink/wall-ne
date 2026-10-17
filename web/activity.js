import {EventBuffer, category, describe, liveSources, linkedSessions} from './activity-data.js';

const $ = id => document.getElementById(id);
let mode = 'live', paused = false, busy = false, timer, failures = 0, lastReceived = null;
let liveBuffer = new EventBuffer(), historyBuffer = new EventBuffer(10000), selectedKey = null, shown = 100;
let sessionRows = [], sessionCursor = null, historySources = [], historyGeneration = 0;
let listing = false, historyLoading = false, historyInitialized = false, selectedSession = '';

// This observer has no mutation API. One bounded live request at a time; no runtime retry/stop calls.
async function read(path) {
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(path, {method: 'GET', cache: 'no-store', signal: controller.signal});
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timeout); }
}
function text(tag, value, className) {
  const node = document.createElement(tag); node.textContent = value;
  if (className) node.className = className;
  return node;
}
function connection(message, stale = false) {
  $('connection').textContent = message; $('connection').dataset.state = stale ? 'stale' : 'connected';
}
function schedule() {
  clearTimeout(timer);
  if (mode === 'live' && !paused && !document.hidden) timer = setTimeout(poll, Math.min(30000, 3000 * 2 ** failures));
}
async function poll() {
  if (busy || paused || mode !== 'live' || document.hidden) return;
  busy = true;
  try {
    const state = await read('/api/state');
    if (mode !== 'live' || paused || document.hidden) return;
    if (!state.id) throw Error('No mission snapshot available');
    for (const source of liveSources(state)) {
      const events = [...(source.events || []), ...Object.values(source.robot_events || {}).flat()];
      const committed = source.storage?.committed_sequence ?? -1;
      liveBuffer.add(source.id, events.filter(e => e.sequence <= committed), true);
      liveBuffer.add(source.id, events.filter(e => e.sequence > committed));
    }
    lastReceived = new Date(); failures = 0;
    const degraded = liveSources(state).some(s => s.storage?.healthy === false || s.storage?.error);
    connection(`Updated ${lastReceived.toLocaleTimeString()} · ${state.id.slice(0, 8)}${degraded ? ' · Storage degraded; live events may not be saved yet.' : ' · Watching current mission and workers.'}`, degraded);
    renderOverview(state); renderEvents();
  } catch (error) {
    failures = Math.min(4, failures + 1);
    if (mode === 'live' && !paused) connection(`Feed unavailable (${error.name === 'AbortError' ? 'request timed out' : error.message}). Keeping received events${lastReceived ? ' from ' + lastReceived.toLocaleTimeString() : ''}; retrying in ${Math.min(30, 3 * 2 ** failures)}s.`, true);
  } finally { busy = false; schedule(); }
}
function renderOverview(state) {
  const sources = liveSources(state), incidents = sources.flatMap(s => (s.incidents?.open || []).map(i => ({...i, session: s.id})));
  $('mission-status').textContent = (state.status || 'unknown').replaceAll('_', ' ');
  $('incident-count').textContent = incidents.length;
  $('pending-count').textContent = state.inference?.pending_calls ?? '—';
  $('failed-count').textContent = state.inference?.failed_calls ?? '—';
  const notices = incidents.map(i => {
    const row = document.createElement('div');
    row.append(text('b', `${i.robot} · ${(i.kind || 'incident').replaceAll('_', ' ')} `), text('span', `${i.detail || ''}${i.response ? ' → ' + i.response.decision + ': ' + i.response.reason : ' · Awaiting response'}`));
    return row;
  });
  for (const s of sources) if (s.escalation) {
    const row = document.createElement('div'); row.append(text('b', 'HUMAN NEEDED · '), text('span', `${s.escalation.robot}: ${s.escalation.reason}`)); notices.unshift(row);
  }
  $('incidents').replaceChildren(...notices);
  const cards = [], children = Object.entries(state.care_workers || {});
  const workers = new Map(Object.keys(state.vehicles || state.telemetry || {}).map(id => [id, state]));
  for (const [id, child] of children) workers.set(id, child);
  const entries = [['Mission / orchestrator', state], ...workers];
  for (const [id, source] of entries) {
    const health = source.health?.[id], sample = source.telemetry?.[id];
    const status = health?.status || source.status || 'unknown';
    const card = text('article', '', 'worker-card');
    card.dataset.attention = String(/blocked|failed|disabled|stale|loop|stalled/.test(status) || !!source.storage?.error);
    const heading = text('h2', id); heading.append(text('span', status.replaceAll('_', ' '))); card.append(heading);
    const wait = health?.waiting_reason || sample?.waiting_reason || source.waiting;
    card.append(text('p', wait ? `Waiting: ${typeof wait === 'string' ? wait.replaceAll('_', ' ') : JSON.stringify(wait)}` : 'No wait reported'));
    if (health) card.append(text('p', `Heartbeat ${Number(health.heartbeat_age || 0).toFixed(1)}s · ${health.failures_without_progress || 0} consecutive failures`));
    if (sample) card.append(text('p', `Progress revision ${sample.last_progress_revision ?? '—'} · ${sample.fault || 'no fault reported'}`));
    if (source !== state || id === 'Mission / orchestrator') card.append(text('p', `${source.inference?.pending_calls ?? 0} calls in flight · ${source.inference?.failed_calls ?? 0} failed calls`));
    if (source.feedback && source !== state) card.append(text('p', source.feedback));
    for (const [role, route] of Object.entries(source.provider_routes || {})) if (route.fallback) card.append(text('p', `${role}: provider fallback active${route.reason ? ' · ' + route.reason : ''}`));
    if (source.storage?.error) card.append(text('p', `Storage: ${source.storage.error}`));
    cards.push(card);
  }
  $('workers').replaceChildren(...cards);
}
function buffer() { return mode === 'live' ? liveBuffer : historyBuffer; }
function renderEvents() {
  const rows = buffer().values(), chosen = $('robot').value;
  const focusedKey = document.activeElement?.dataset?.eventKey;
  const scrollTop = $('events').scrollTop;
  const robots = [...new Set(rows.map(e => e.robot_id || 'SYS'))].sort();
  if ([...$('robot').options].slice(1).map(o => o.value).join('|') !== robots.join('|')) $('robot').replaceChildren(new Option('All robots and roles', ''), ...robots.map(r => new Option(r, r)));
  if (robots.includes(chosen)) $('robot').value = chosen;
  const needle = $('search').value.trim().toLowerCase();
  const filtered = rows.filter(e => (!$('robot').value || (e.robot_id || 'SYS') === $('robot').value) && (!$('category').value || category(e) === $('category').value) && (!needle || `${e.type} ${e.robot_id} ${e.session} ${JSON.stringify(e.payload)}`.toLowerCase().includes(needle)));
  $('event-count').textContent = `${filtered.length} matching / ${rows.length} received`;
  $('coverage').textContent = mode === 'live'
    ? `Recent snapshots only · newest first · heartbeats hidden · up to 2,000 events kept in this tab. Gaps can occur while disconnected or between polls; use Past sessions for saved evidence.${liveBuffer.evicted ? ' Older received events have left the buffer.' : ''}`
    : `Saved events · newest loaded first · heartbeats hidden. Load next saved events to move forward through the session.${historyBuffer.evicted ? ' Earlier loaded events have left the 10,000-event buffer; reselect the session to read them again.' : ''}`;
  const list = filtered.slice(0, shown).map(e => {
    const button = text('button', '', 'activity-event'); button.type = 'button'; button.dataset.eventKey = e.key; button.dataset.category = category(e); button.setAttribute('aria-pressed', String(e.key === selectedKey));
    const time = text('time', e.wall_utc ? new Date(e.wall_utc).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : `${Number(e.sim_time || 0).toFixed(1)}s`); time.title = e.wall_utc || ''; if(e.wall_utc) time.dateTime = e.wall_utc;
    const source = text('span', e.robot_id || 'SYS', 'source'); source.append(text('small', e.session.slice(0, 8)));
    const content = document.createElement('span'); content.append(text('span', e.type.replaceAll('_', ' '), 'event-type'), text('span', describe(e), 'description'));
    button.append(time, source, content); button.onclick = () => {selectedKey = e.key; renderDetail(e); renderEvents();}; return button;
  });
  $('events').replaceChildren(...(list.length ? list : [text('p', rows.length ? 'No events match these filters.' : mode === 'live' ? 'Waiting for activity. Received events will appear here.' : 'No visible events loaded. Choose a session or load the next saved events.', 'empty')]));
  $('events').scrollTop = scrollTop;
  if (focusedKey) list.find(node => node.dataset.eventKey === focusedKey)?.focus({preventScroll: true});
  const selected = rows.find(e => e.key === selectedKey);
  if (selected) renderDetail(selected);
  $('show-more').hidden = filtered.length <= shown;
}
function renderDetail(e) {
  const detail = $('event-detail'), dl = document.createElement('dl');
  for (const [label, value] of Object.entries({Robot: e.robot_id || 'SYS', Session: e.session, Sequence: e.sequence, Recorded: e.wall_utc || 'Unknown', 'Sim time': `${e.sim_time}s`, Evidence: e.durable ? 'Saved / committed' : 'Live snapshot · persistence unconfirmed'})) dl.append(text('dt', label), text('dd', String(value)));
  detail.replaceChildren(text('h2', e.type.replaceAll('_', ' ')), text('p', describe(e)), dl, text('pre', JSON.stringify(e.payload || {}, null, 2)));
}
function resetDetail() { selectedKey = null; $('event-detail').replaceChildren(text('h2', 'Follow the evidence'), text('p', 'Select an event to inspect its full recorded payload.')); }
function setMode(next) {
  mode = next; clearTimeout(timer); shown = 100; resetDetail();
  $('live').classList.toggle('primary', mode === 'live'); $('history').classList.toggle('primary', mode === 'history');
  $('live').setAttribute('aria-pressed', String(mode === 'live')); $('history').setAttribute('aria-pressed', String(mode === 'history'));
  $('history-panel').hidden = $('history-actions').hidden = mode !== 'history';
  $('live-overview').hidden = $('watch').hidden = mode !== 'live'; $('feed-heading').textContent = mode === 'live' ? 'Incoming activity' : 'Saved activity';
  renderEvents();
  if (mode === 'live') { connection(paused ? 'Feed paused. Robot execution is unchanged.' : 'Connecting to the live feed…'); poll(); }
  else { connection('Browsing saved evidence. Robot execution is unchanged.'); if (!sessionRows.length) refreshSessions(); }
}
async function refreshSessions(older = false) {
  if (listing) return;
  listing = true; $('refresh-sessions').disabled = $('older-sessions').disabled = true;
  try {
    const suffix = older && sessionCursor ? `?before=${encodeURIComponent(sessionCursor.started_at)}&before_id=${encodeURIComponent(sessionCursor.id)}` : '';
    const rows = await read('/api/sessions' + suffix);
    sessionRows = older ? [...sessionRows, ...rows] : rows; sessionCursor = rows.at(-1) || (older ? sessionCursor : null);
    const options = sessionRows.map(s => new Option(`${new Date(s.started_at).toLocaleString()} · ${s.kind} · ${s.status} · ${s.id.slice(0, 8)}${s.metadata?.configuration?.parent_session_id ? ' · worker of ' + s.metadata.configuration.parent_session_id.slice(0, 8) : ''}`, s.id));
    if (selectedSession && !sessionRows.some(s => s.id === selectedSession)) options.unshift(new Option(selectedSession, selectedSession));
    $('session').replaceChildren(new Option('Choose a session', ''), ...options); $('session').value = selectedSession;
    $('history-status').textContent = `${sessionRows.length} sessions listed. Selecting a fleet session includes its linked workers.`;
    $('older-sessions').hidden = rows.length < 50;
  } catch (error) { $('history-status').textContent = `Session list unavailable (${error.message}). Existing events remain available. Retry when storage returns.`; }
  finally { listing = false; $('refresh-sessions').disabled = $('older-sessions').disabled = false; }
}
async function selectSession(id) {
  const generation = ++historyGeneration;
  selectedSession = id; historySources = []; historyInitialized = false; historyLoading = false;
  historyBuffer = new EventBuffer(10000); shown = 100; resetDetail(); renderEvents();
  $('next-events').disabled = !id; $('page-status').textContent = '';
  if (!id) return;
  historySources = [{id, cursor: 0, done: false}];
  await loadHistory(generation);
}
async function loadHistory(generation = historyGeneration) {
  if (historyLoading || !historySources.length) return;
  historyLoading = true; $('next-events').disabled = true;
  $('page-status').textContent = 'Reading saved evidence…';
  try {
    let linkWarning = '';
    if (!historyInitialized) {
      // Explicit history reads only. This does not restore or resume a session.
      try {
        const exported = await read(`/api/sessions/${encodeURIComponent(selectedSession)}/export`);
        if (generation !== historyGeneration) return;
        if (exported.checkpoint_integrity?.valid === false) throw Error('Checkpoint integrity check failed');
        historySources.push(...linkedSessions(exported.checkpoint).filter(id => !historySources.some(s => s.id === id)).map(id => ({id, cursor: 0, done: false})));
        historyInitialized = true;
      } catch (error) {
        if (generation !== historyGeneration) return;
        linkWarning = ` Worker links may be incomplete (${error.message}); saved events can still be read.`;
      }
    }
    // Sequential, user-requested pagination avoids a burst of storage reads.
    const source = historySources.find(s => !s.done);
    if (source) {
      const rows = await read(`/api/sessions/${encodeURIComponent(source.id)}/events?after=${source.cursor}`);
      if (generation !== historyGeneration) return;
      historyBuffer.add(source.id, rows, true);
      if (rows.length) source.cursor = rows.at(-1).sequence;
      source.done = rows.length < 100;
      // Round-robin sources so a long parent heartbeat history cannot hide workers.
      historySources = [...historySources.filter(s => s !== source), source];
      // Dispatch records also link children when older checkpoints lack the registry.
      for (const e of rows) if (['worker_dispatched', 'worker_finished'].includes(e.type) && e.payload?.session_id && !historySources.some(s => s.id === e.payload.session_id)) historySources.push({id: e.payload.session_id, cursor: 0, done: false});
    }
    const remaining = historySources.filter(s => !s.done).length;
    $('page-status').textContent = remaining ? `${historySources.length} linked sessions · ${remaining} still have events to read. Loaded through sequence ${source?.cursor || 0} of ${source?.id.slice(0, 8)}.` : `All currently saved events loaded from ${historySources.length} sessions. Reselect to check for newer saved events.`;
    $('page-status').textContent += linkWarning;
    if (mode === 'history') renderEvents();
  } catch (error) {
    if (generation === historyGeneration) $('page-status').textContent = `History unavailable (${error.message}). Received events retained. Use Load next saved events to retry.`;
  } finally {
    if (generation === historyGeneration) { historyLoading = false; $('next-events').disabled = !historySources.some(s => !s.done); }
  }
}
$('live').onclick = () => setMode('live'); $('history').onclick = () => setMode('history');
$('watch').onclick = () => {
  paused = !paused; clearTimeout(timer); $('watch').textContent = paused ? 'Resume feed' : 'Pause feed'; $('watch').setAttribute('aria-pressed', String(paused));
  connection(paused ? 'Feed paused. Robot execution is unchanged.' : 'Reconnecting…'); if (!paused) poll();
};
for (const id of ['robot', 'category', 'search']) $(id).addEventListener('input', () => {shown = 100; renderEvents();});
$('show-more').onclick = () => {shown += 100; renderEvents();};
$('refresh-sessions').onclick = () => refreshSessions(); $('older-sessions').onclick = () => refreshSessions(true);
$('session').onchange = () => selectSession($('session').value); $('next-events').onclick = () => loadHistory();
document.addEventListener('visibilitychange', () => {
  clearTimeout(timer);
  if (mode !== 'live' || paused) return;
  if (document.hidden) connection('Feed suspended while this tab is hidden. Robot execution is unchanged.');
  else poll();
});
const initialSession = new URLSearchParams(location.search).get('session');
if (initialSession && /^[0-9a-f-]{36}$/i.test(initialSession)) {setMode('history'); selectSession(initialSession);}
else poll();
