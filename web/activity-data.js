// Read-only projections shared by the activity page and its contract tests.
const noise = new Set(['heartbeat', 'checkpoint']);
const attention = /error|failed|fault|stall|reject|blocked|breakdown|escalation|loop|slip|dropped|cancelled|timeout/;
export function category(event) {
  if (event.type === 'incident_resolved' || event.type === 'recovered') return 'recovery';
  if (event.type === 'incident' || attention.test(event.type) || /blocked|failed|aborted/.test(event.payload?.status || '')) return 'attention';
  if (event.type === 'provider_fallback' || event.type === 'incident_response') return 'recovery';
  return 'activity';
}
export function describe(event) {
  const p = event.payload || {}, d = p.result?.decision;
  if (d) return `${d.action || 'Decision'}${d.rationale ? ' · ' + d.rationale : ''}`;
  if (event.type === 'provider_fallback') return `${p.from_provider || '?'} / ${p.from_model || '?'} → ${p.to_provider || '?'} / ${p.to_model || '?'} · ${p.reason || ''}`;
  if (event.type === 'incident_response') return `${p.target || ''} → ${p.decision || ''} · ${p.reason || ''}`;
  return p.error || p.reason || p.detail || p.receipt?.reason || p.receipt?.action || p.action || p.status || p.incident_kind || 'Recorded event';
}
export function liveSources(state) {
  return [state, ...Object.values(state.care_workers || {})].filter(s => s?.id);
}
export function linkedSessions(checkpoint) {
  return [...new Set([
    ...Object.keys(checkpoint?.worker_sessions || {}),
    ...Object.keys(checkpoint?.results || {}),
    ...Object.values(checkpoint?.assignments || {}).map(a => a.session_id),
  ].filter(Boolean))];
}
export class EventBuffer {
  constructor(limit = 2000) { this.limit = limit; this.rows = new Map(); this.evicted = 0; }
  add(session, events, durable = false) {
    for (const event of events || []) {
      if (noise.has(event.type)) continue;
      const key = `${session}:${event.sequence}`;
      const old = this.rows.get(key);
      this.rows.set(key, {...event, session, key, durable: durable || old?.durable || false});
    }
    const sorted = this.values();
    for (const e of sorted.slice(this.limit)) { this.rows.delete(e.key); this.evicted++; }
  }
  values() {
    return [...this.rows.values()].sort((a, b) => (b.wall_utc || '').localeCompare(a.wall_utc || '') || b.sequence - a.sequence || a.session.localeCompare(b.session));
  }
}
