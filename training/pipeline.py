"""Durable teacher queue and reproducible policy datasets (standard library only)."""
import copy
import gzip
import json
import math
import sqlite3
import uuid
from pathlib import Path

from simulator.common import canonical, digest, utc
from simulator.inference import InferenceError


class Pipeline:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS inputs (
            id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, split_group TEXT NOT NULL,
            payload TEXT NOT NULL, source TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS evidence (
            session_id TEXT, sequence INTEGER, payload TEXT NOT NULL,
            PRIMARY KEY(session_id, sequence));
          CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY, session_id TEXT, metadata TEXT NOT NULL, content BLOB);
          CREATE TABLE IF NOT EXISTS labels (
            input_id TEXT REFERENCES inputs(id), teacher TEXT, status TEXT NOT NULL,
            result TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY(input_id, teacher));
        ''')

    def close(self):
        self.db.close()

    def add_input(self, payload, source):
        if payload.get('schema_version') != 1:
            raise ValueError('Unsupported policy input version')
        if digest(payload) != source['policy_input_hash']:
            raise ValueError('Policy input hash mismatch')
        if digest(payload['observation']) != source['observation_hash']:
            raise ValueError('Observation hash mismatch')
        body = payload['body']
        if json.loads(body['messages'][1]['content'][0]['text']) != payload['observation']:
            raise ValueError('Wire observation differs from recorded observation')
        content_hash = digest({k: body[k] for k in ('messages', 'tools')})
        groups = source.get('split_groups') or ['seed:' + str(source['seed'])]
        values = (payload['request_id'], content_hash, min(groups),
                  canonical(payload), canonical(source))
        previous = self.db.execute('SELECT * FROM inputs WHERE id=?', (values[0],)).fetchone()
        if previous and tuple(previous) != values:
            raise ValueError('Conflicting immutable input')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO inputs VALUES (?,?,?,?,?)', values)
        return previous is None

    def export_sessions(self, repository, sessions, include_telemetry=False):
        """Freeze each session at its committed boundary; include linked child sessions."""
        pending = list(sessions)
        seen = set()
        session_cache = {}
        report = dict(imported=0, legacy_skipped=0, sessions=0)
        while pending:
            sid = str(uuid.UUID(pending.pop(0)))
            if sid in seen:
                continue
            seen.add(sid)
            rows = repository.read('sessions', 'id=eq.' + sid + '&limit=1')
            if not rows:
                raise ValueError('Unknown session ' + sid)
            session = rows[0]
            session_cache[sid] = session
            groups = lineage_groups(repository, sid, session_cache)
            cutoff = session['committed_sequence']
            for child in pages(repository, 'sessions',
                               'metadata->configuration->>parent_session_id=eq.' + sid, 'id'):
                pending.append(child['id'])
            for event in pages(repository, 'events',
                               f'session_id=eq.{sid}&sequence=lte.{cutoff}', 'sequence'):
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO evidence VALUES (?,?,?)',
                                    (sid, event['sequence'], canonical(event)))
                if event['type'] != 'inference_requested':
                    continue
                request = event['payload']['request']
                artifact_id = request.get('policy_input_artifact_id')
                if not artifact_id:
                    report['legacy_skipped'] += 1
                    continue
                raw, artifact = repository.artifact_bytes(sid, str(uuid.UUID(artifact_id)))
                if (not artifact.get('ready') or artifact['kind'] != 'policy_input'
                        or artifact['sequence'] > cutoff
                        or artifact['metadata']['request_id'] != request['id']):
                    raise ValueError('Uncommitted or mismatched policy input artifact')
                payload = json.loads(gzip.decompress(raw))
                if payload['request_id'] != request['id']:
                    raise ValueError('Request/artifact mismatch')
                # Keep provenance separate: none of this goes into teacher/student prompts.
                source = dict(request, seed=session['seed'], event_sequence=event['sequence'],
                              session_id=sid, robot_id=event['robot_id'], artifact_id=artifact_id,
                              split_groups=sorted(groups))
                report['imported'] += self.add_input(payload, source)
            for artifact in pages(repository, 'artifacts',
                                  f'session_id=eq.{sid}&sequence=lte.{cutoff}', 'id'):
                content = None
                if include_telemetry and artifact['kind'] == 'movement':
                    content, _ = repository.artifact_bytes(sid, artifact['id'])
                with self.db:
                    self.db.execute('INSERT INTO artifacts VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET content=COALESCE(excluded.content,artifacts.content)',
                                    (artifact['id'], sid, canonical(artifact), content))
            report['sessions'] += 1
        return report

    def enqueue(self, teacher, modality='text'):
        if not teacher.strip():
            raise ValueError('Explicit teacher model is required')
        if modality not in ('text', 'multimodal'):
            raise ValueError('Choose text or multimodal teacher inputs')
        with self.db:
            for row in self.db.execute('SELECT id,payload FROM inputs').fetchall():
                body = json.loads(row['payload'])['body']
                images = any(p.get('type') == 'image_url' for p in body['messages'][1]['content'])
                if images == (modality == 'multimodal'):
                    self.db.execute("INSERT OR IGNORE INTO labels VALUES (?,?,'pending',NULL,?)",
                                    (row['id'], teacher, utc()))

    def complete(self, input_id, teacher, result):
        row = self.db.execute('SELECT payload FROM inputs WHERE id=?', (input_id,)).fetchone()
        if not row:
            raise ValueError('Unknown input')
        payload = json.loads(row['payload'])
        if result.get('input_hash') != digest(payload):
            raise ValueError('Teacher label input hash mismatch')
        if result.get('requested_model') != teacher or not result.get('returned_model'):
            raise ValueError('Teacher model provenance missing or mismatched')
        decision = result['decision']
        completion = completion_for(payload, decision)
        saved = dict(result, completion=completion, physical_validation='not_executed')
        with self.db:
            previous = self.db.execute('SELECT status,result FROM labels WHERE input_id=? AND teacher=?',
                                       (input_id, teacher)).fetchone()
            if previous and previous['status'] == 'done':
                if previous['result'] != canonical(saved):
                    raise ValueError('Conflicting immutable label')
                return
            self.db.execute('INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?)',
                            (input_id, teacher, 'done', canonical(saved), utc()))

    def label(self, adapter, max_calls, cost_cap, modality='text'):
        """Claim before HTTP. A crash leaves inflight work for explicit human reconciliation."""
        if max_calls <= 0 or not math.isfinite(cost_cap) or cost_cap <= 0:
            raise ValueError('Positive call and reported-cost caps are required')
        teacher = adapter.model
        self.enqueue(teacher, modality)
        calls, cost, stopped = 0, 0.0, None
        while calls < max_calls and cost < cost_cap:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                row = self.db.execute('''SELECT inputs.* FROM inputs JOIN labels ON inputs.id=labels.input_id
                    WHERE teacher=? AND status='pending' ORDER BY inputs.id''', (teacher,)).fetchall()
                row = next((r for r in row if any(p.get('type') == 'image_url' for p in json.loads(r['payload'])['body']['messages'][1]['content']) == (modality == 'multimodal')), None)
                if not row:
                    break
                self.db.execute("UPDATE labels SET status='inflight',updated_at=? WHERE input_id=? AND teacher=?",
                                (utc(), row['id'], teacher))
            payload = json.loads(row['payload'])
            calls += 1
            result = None
            try:
                result = adapter.call_body(copy.deepcopy(payload['body']))
                result['input_hash'] = digest(payload)
                self.complete(row['id'], teacher, result)
            except (InferenceError, ValueError, KeyError, TypeError) as exc:
                # Keep billed failure metrics; do not retry an ambiguous paid request.
                with self.db:
                    self.db.execute("UPDATE labels SET status='failed',result=?,updated_at=? WHERE input_id=? AND teacher=?",
                                    (canonical(dict(error=type(exc).__name__, reason=str(exc)[:1200],
                                                   response=result, metrics=getattr(exc,'metrics',None))),
                                     utc(), row['id'], teacher))
                stopped = 'teacher_error'; break
            reported = result.get('cost')
            if not isinstance(reported, (float, int)) or not math.isfinite(reported) or reported < 0:
                stopped = 'unknown_cost'; break
            cost += reported
        return dict(calls=calls, reported_cost=cost, stopped=stopped)

    def build(self, output, teacher, validation_percent=20):
        if not 1 <= validation_percent <= 99:
            raise ValueError('Validation percentage must be between 1 and 99')
        rows = self.db.execute('''SELECT inputs.*,labels.result FROM inputs JOIN labels ON inputs.id=labels.input_id
            WHERE labels.teacher=? AND labels.status='done' ORDER BY inputs.id''', (teacher,)).fetchall()
        if not rows:
            raise ValueError('No validated teacher labels')
        # Identical prompts across seeds must not land in both splits. Union their seed groups.
        memberships = {r['id']: json.loads(r['source']).get('split_groups') or [r['split_group']] for r in rows}
        parents = {group: group for groups in memberships.values() for group in groups}
        def root(group):
            while parents[group] != group:
                group = parents[group]
            return group
        for groups in memberships.values():
            for group in groups[1:]:
                left, right = root(groups[0]), root(group)
                parents[max(left, right)] = min(left, right)
        hashes = {}
        for row in rows:
            group = root(row['split_group'])
            if row['content_hash'] in hashes:
                other = root(hashes[row['content_hash']])
                parents[max(group, other)] = min(group, other)
            hashes[row['content_hash']] = row['split_group']
        files = {name: [] for name in ('train.jsonl', 'validation.jsonl', 'multimodal.jsonl', 'provenance.jsonl')}
        used = set()
        for row in rows:
            if row['content_hash'] in used:
                continue
            used.add(row['content_hash'])
            payload, result = json.loads(row['payload']), json.loads(row['result'])
            completion = completion_for(payload, result['decision'])
            group = root(row['split_group'])
            split = 'validation' if int(digest(group)[:8], 16) % 100 < validation_percent else 'train'
            example = dict(prompt=copy.deepcopy(payload['body']['messages']), completion=[completion],
                           tools=payload['body']['tools'])
            multimodal = any(part.get('type') == 'image_url' for part in example['prompt'][1]['content'])
            if not multimodal:
                example['prompt'][1]['content'] = example['prompt'][1]['content'][0]['text']
            name = 'multimodal.jsonl' if multimodal else split + '.jsonl'
            files[name].append(canonical(example))
            files['provenance.jsonl'].append(canonical(dict(input_id=row['id'], input_hash=digest(payload),
                content_hash=row['content_hash'], group=group, split=split, file=name, source=json.loads(row['source']),
                teacher=teacher, returned_model=result['returned_model'], response_id=result.get('response_id'),
                physical_validation='not_executed')))
        contents = {name: ('\n'.join(lines) + ('\n' if lines else '')).encode() for name, lines in files.items()}
        import hashlib
        manifest = dict(schema_version=1, teacher=teacher, validation_percent=validation_percent,
                        split_policy='root/continuation/season seed groups unioned by identical input; sha256 modulo 100',
                        physical_validation='not_executed', files={name: dict(rows=len(files[name]),
                            sha256=hashlib.sha256(raw).hexdigest()) for name, raw in contents.items()})
        manifest['dataset_id'] = digest(manifest)
        output = Path(output)
        output.mkdir(parents=True, exist_ok=False)
        for name, raw in contents.items():
            (output / name).write_bytes(raw)
        (output / 'manifest.json').write_text(canonical(manifest) + '\n')
        return manifest


def lineage_groups(repository, session_id, cache, visiting=None):
    """Follow both parent and continuation edges; season seed is stable across days."""
    visiting = set() if visiting is None else visiting
    if session_id in visiting:
        raise ValueError('Cyclic session lineage')
    visiting = visiting | {session_id}
    if session_id not in cache:
        rows = repository.read('sessions', 'id=eq.' + str(uuid.UUID(session_id)) + '&limit=1')
        if not rows:
            raise ValueError('Missing session lineage; cannot safely split')
        cache[session_id] = rows[0]
    session = cache[session_id]
    config = session.get('metadata', {}).get('configuration', {})
    groups = {'seed:' + str(session['seed'])}
    if config.get('season_seed') is not None:
        groups.add('seed:' + str(config['season_seed']))
    for key in ('parent_session_id', 'continuation_source'):
        if config.get(key):
            groups.update(lineage_groups(repository, config[key], cache, visiting))
    return groups


def pages(repository, table, filters, key):
    """Keyset pagination continues even when the backend caps a page below our limit."""
    cursor = None
    while True:
        query = filters + f'&order={key}.asc&limit=250'
        if cursor is not None:
            query += f'&{key}=gt.{cursor}'
        rows = repository.read(table, query)
        if not rows:
            return
        if cursor is not None and rows[-1][key] <= cursor:
            raise ValueError('Non-advancing export cursor')
        yield from rows
        cursor = rows[-1][key]


def validate_schema(value, schema):
    """Validate the JSON-schema subset used by our action tools; reject nonfinite numbers."""
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'boolean': type(value) is bool,
             'integer': type(value) is int,
             'number': type(value) in (int, float) and math.isfinite(value)}
    if kind and not valid.get(kind, False):
        raise ValueError('Invalid tool argument type')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('Action is not available')
    if kind == 'object':
        if set(schema.get('required', [])) - set(value):
            raise ValueError('Missing tool argument')
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            raise ValueError('Unknown tool argument')
        for key, item in value.items():
            validate_schema(item, properties.get(key, {}))
    if kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', math.inf):
            raise ValueError('Invalid tool array length')
        for item in value:
            validate_schema(item, schema.get('items', {}))
    if kind in ('number', 'integer'):
        if not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):
            raise ValueError('Tool argument outside range')


def completion_for(payload, decision):
    observation = payload['observation']
    tool = payload['body']['tools'][0]['function']
    action, arguments = decision['action'], copy.deepcopy(decision['arguments'])
    if not isinstance(action, str) or not isinstance(arguments, dict):
        raise ValueError('Malformed teacher decision')
    if set(decision) - {'action', 'arguments', 'rationale'}:
        raise ValueError('Unknown teacher decision field')
    rationale = decision.get('rationale', '')
    if not isinstance(rationale, str) or len(rationale) > 1200:
        raise ValueError('Invalid rationale')
    if 'available_actions' in observation and action not in observation['available_actions']:
        raise ValueError('Unavailable action')
    validate_action_arguments(action, arguments, observation)
    options = observation.get('feasible_options')
    if options is not None and not any(action == opt['action'] and arguments == opt.get('arguments', {}) for opt in options):
        raise ValueError('Teacher did not select a feasible option')
    frame = observation.get('frame') or {}
    if 'frame_id' in arguments and frame.get('id') and arguments['frame_id'] != frame['id']:
        raise ValueError('Stale teacher frame')
    if tool['name'] == 'choose_action':
        wire = dict(action=action, arguments=arguments, rationale=rationale)
    else:
        if tool['name'] == 'treatment_action' and action == 'move_arm' and 'pose' in arguments:
            pose = arguments.pop('pose')
            if len(pose) != 6:
                raise ValueError('Invalid pose')
            arguments.update(zip(('x', 'y', 'z', 'rx', 'ry', 'rz'), pose))
        wire = dict(arguments, action=action, reason=rationale)
    validate_schema(wire, tool['parameters'])
    return dict(role='assistant', content='', tool_calls=[dict(type='function',
                function=dict(name=tool['name'], arguments=wire))])


# Structural requirements from Treatment/Care/Manipulation._action. These do not
# assert that a grasp, contact, collision-free move or other physical outcome succeeds.
ACTION_REQUIRED = {
    'aim_nozzle': ('u', 'v', 'frame_id'), 'remove_weed': ('u', 'v', 'frame_id'),
    'remove_pest': ('u', 'v', 'frame_id'), 'scan_lidar': ('u', 'v', 'frame_id'),
    'measure_depth': ('u', 'v', 'frame_id'), 'project_ground': ('u', 'v', 'frame_id'),
    'dispense': ('liters', 'frame_id'), 'fertilize': ('grams', 'frame_id'),
    'select_tool': ('tool',), 'set_gripper': ('opening', 'force'),
    'assess_alignment': ('frame_id', 'stem_between_fingers', 'depth_consistent', 'evidence'),
    'confirm_contact': ('frame_id', 'evidence'),
}


def validate_action_arguments(action, arguments, observation):
    if set(ACTION_REQUIRED.get(action, ())) - set(arguments):
        raise ValueError('Missing action-specific arguments')
    if action == 'move_arm' and ('pose' in arguments) == ('joints' in arguments):
        raise ValueError('move_arm needs exactly one pose or joints array')
    if 'evidence' in arguments and (not isinstance(arguments['evidence'], str)
                                     or not 8 <= len(arguments['evidence'].strip()) <= 600):
        raise ValueError('Invalid action evidence length')
    if action == 'select_tool' and arguments['tool'] not in ('nozzle', 'gripper', 'fertilizer', 'vacuum'):
        raise ValueError('Unknown fitted tool')
    expected = {'contract planner': 'accept_contract', 'independent verifier explanation': 'verify'}
    if observation.get('role') in expected and action != expected[observation['role']]:
        raise ValueError('Action is not available for this role')
