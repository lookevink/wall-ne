import test from 'node:test';
import assert from 'node:assert/strict';
import {EventBuffer, category, describe, liveSources, linkedSessions} from '../web/activity-data.js';

test('worker snapshots stay independent from parent projections', () => {
  const child = {id:'child', events:[{sequence:1,type:'inference_error'}], health:{W1:{status:'possible_loop'}}};
  const parent = {id:'parent', care_workers:{W1:child}, health:{W1:{status:'healthy'}}};
  assert.deepEqual(liveSources(parent), [parent, child]);
  assert.equal(parent.health.W1.status, 'healthy');
});
test('event identity includes source session; persistence confirmation can advance', () => {
  const buffer = new EventBuffer();
  const e = {sequence:2,type:'inference_error',wall_utc:'2026-10-17T10:00:00Z'};
  buffer.add('parent', [e]); buffer.add('child', [e]); buffer.add('child', [e], true); buffer.add('child', [e]);
  assert.equal(buffer.values().length, 2);
  assert.equal(buffer.values().find(e => e.session === 'child').durable, true);
  assert.equal(buffer.values().find(e => e.session === 'parent').durable, false);
});
test('bounded live buffer orders wall times across independent simulation clocks', () => {
  const buffer = new EventBuffer(2);
  buffer.add('a', [{sequence:100,type:'decision',sim_time:100,wall_utc:'2026-10-17T10:00:00Z'}, {sequence:101,type:'heartbeat'}, {sequence:102,type:'checkpoint'}]);
  buffer.add('b', [{sequence:1,type:'incident',sim_time:0,wall_utc:'2026-10-17T10:00:01Z'}, {sequence:2,type:'escalation',sim_time:1,wall_utc:'2026-10-17T10:00:02Z'}]);
  assert.deepEqual(buffer.values().map(e=>e.type), ['escalation','incident']);
  assert.equal(buffer.evicted, 1);
});
test('history discovers completed, superseded, and active workers without duplicates', () => {
  assert.deepEqual(linkedSessions({worker_sessions:{old:{},active:{}},results:{old:{},completed:{}},assignments:{0:{session_id:'active'},1:{session_id:null}}}), ['old','active','completed']);
});
test('attention and recovery filters retain meaningful failure and routing reasons', () => {
  assert.equal(category({type:'inference_error'}), 'attention');
  assert.equal(category({type:'loop_incident'}), 'attention');
  assert.equal(category({type:'incident_resolved'}), 'recovery');
  assert.equal(category({type:'provider_fallback'}), 'recovery');
  assert.match(describe({type:'provider_fallback',payload:{from_provider:'crusoe',from_model:'nano',to_provider:'gateway',to_model:'super',reason:'timeout'}}), /crusoe \/ nano → gateway \/ super · timeout/);
  assert.equal(describe({type:'decision',payload:{result:{decision:{action:'observe',rationale:'Get new evidence'}}}}), 'observe · Get new evidence');
});
