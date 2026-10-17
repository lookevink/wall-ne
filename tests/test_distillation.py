import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from simulator.common import canonical, digest, uid
from simulator.engine import Mission
from simulator.inference import Adapter, InferenceError, build_request
from simulator.persistence import StorageError
from simulator.runtime import Runtime
from training.pipeline import Pipeline, completion_for, pages, lineage_groups
from training.train import check_dataset, render_example

TEACHER = 'larger-teacher'


def fixture(seed=7, image=None, observation=None):
    observation = observation or dict(role='worker', robot='W1', seed=seed,
        feasible_options=[dict(action='inspect', arguments=dict(zone='Z1', ownership_version=1))])
    payload = dict(schema_version=1, request_id=uid(), observation=observation,
                   body=build_request(observation, image, 'Pinned robot prompt', 'student'))
    source = dict(seed=seed, session_id=uid(), policy_input_hash=digest(payload),
                  observation_hash=digest(observation), synthetic=True)
    return payload, source


def result(payload, decision=None):
    return dict(input_hash=digest(payload), requested_model=TEACHER, returned_model=TEACHER,
                response_id='fake-response', cost=.01, decision=decision or
                dict(action='inspect', arguments=dict(zone='Z1', ownership_version=1), rationale='Inspect first'))


class DistillationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline(self.root / 'queue.sqlite3')
        self.addCleanup(self.pipeline.close)

    def add(self, **kwargs):
        payload, source = fixture(**kwargs)
        self.pipeline.add_input(payload, source)
        return payload, source

    def test_input_integrity_dedup_and_no_outcome_in_teacher_request(self):
        payload, source = self.add()
        self.assertFalse(self.pipeline.add_input(payload, source))
        bad = copy.deepcopy(payload); bad['observation']['seed'] = 9
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.pipeline.add_input(bad, source)
        source['future_outcome'] = 'failed'
        self.assertNotIn('future_outcome', canonical(payload['body']))

    def test_labels_preserve_provenance_and_reject_invalid_actions(self):
        payload, _ = self.add()
        for decision in (dict(action='water', arguments={}),
                         dict(action='inspect', arguments=dict(zone='Z9', ownership_version=1))):
            with self.assertRaises(ValueError):
                self.pipeline.complete(payload['request_id'], TEACHER, result(payload, decision))
        bad = result(payload); bad['input_hash'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.pipeline.complete(payload['request_id'], TEACHER, bad)
        self.pipeline.complete(payload['request_id'], TEACHER, result(payload))
        saved = json.loads(self.pipeline.db.execute('SELECT result FROM labels').fetchone()[0])
        self.assertEqual(saved['physical_validation'], 'not_executed')
        self.assertEqual(saved['completion']['tool_calls'][0]['function']['arguments']['action'], 'inspect')

    def test_capture_storage_barrier_and_exact_inputs(self):
        with patch('threading.Thread.start'):
            runtime = Runtime(world=Mission(), config=dict(mode='live', engine='crusoe'))
        self.addCleanup(runtime.close)
        runtime.world.status = 'running'
        runtime.repository = Mock()
        runtime.repository.artifact.side_effect = StorageError('upload unavailable')
        adapter = Mock(model='student', provider='crusoe', base='https://example.invalid')
        with patch.object(runtime, 'adapter', return_value=adapter), patch.object(runtime, 'persist', return_value=True):
            self.assertFalse(runtime.dispatch('W1', 'worker', {'sensor': 1}))
        adapter.call.assert_not_called()
        runtime.storage_error = None
        runtime.repository.artifact.side_effect = None
        runtime.repository.artifact.return_value = dict(id='artifact')
        adapter.call.return_value = dict(decision={}, cost=0, usage={})
        observation = dict(sensor=1)
        with patch.object(runtime, 'adapter', return_value=adapter), patch.object(runtime, 'persist', return_value=False):
            self.assertFalse(runtime.dispatch('W1', 'worker', observation))
        adapter.call.assert_not_called()
        payload = runtime.repository.artifact.call_args.args[3]
        self.assertEqual(payload['body'], build_request(observation, model='student'))
        self.assertNotIn('checkpoint', payload)
        self.assertEqual(runtime.requests['W1']['policy_input_hash'], digest(payload))
        observation['sensor'] = 99
        self.assertEqual(payload['observation']['sensor'], 1)

    def test_teacher_crash_is_not_automatically_rebilled(self):
        payload, _ = self.add()
        adapter = Mock(model=TEACHER)
        adapter.call_body.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.pipeline.label(adapter, 2, 1)
        self.assertEqual(self.pipeline.db.execute('SELECT status FROM labels').fetchone()[0], 'inflight')
        adapter.call_body.side_effect = None
        adapter.call_body.return_value = result(payload)
        self.assertEqual(self.pipeline.label(adapter, 2, 1)['calls'], 0)
        self.pipeline.complete(payload['request_id'], TEACHER, result(payload))
        self.assertEqual(self.pipeline.db.execute('SELECT status FROM labels').fetchone()[0], 'done')

    def test_unknown_cost_stops_and_resume_does_not_repeat_done(self):
        payload, _ = self.add()
        adapter = Mock(model=TEACHER)
        adapter.call_body.return_value = dict(result(payload), cost=None)
        self.assertEqual(self.pipeline.label(adapter, 10, 1)['stopped'], 'unknown_cost')
        self.assertEqual(self.pipeline.label(adapter, 10, 1)['calls'], 0)
        self.assertEqual(adapter.call_body.call_count, 1)

    def test_teacher_failures_keep_metrics_and_do_not_retry(self):
        self.add()
        adapter = Mock(model=TEACHER)
        adapter.call_body.side_effect = InferenceError('bad reply', dict(cost=.1))
        self.assertEqual(self.pipeline.label(adapter, 10, 1)['stopped'], 'teacher_error')
        self.assertEqual(self.pipeline.label(adapter, 10, 1)['calls'], 0)
        self.assertEqual(json.loads(self.pipeline.db.execute('SELECT result FROM labels').fetchone()[0])['metrics']['cost'], .1)

    def test_text_and_image_teachers_are_separate(self):
        text, _ = self.add()
        vision, _ = self.add(image='data:image/png;base64,FAKE')
        self.pipeline.enqueue(TEACHER)
        rows = self.pipeline.db.execute('SELECT input_id FROM labels').fetchall()
        self.assertEqual([r[0] for r in rows], [text['request_id']])
        self.pipeline.enqueue(TEACHER, 'multimodal')
        adapter = Mock(model=TEACHER)
        adapter.call_body.return_value = result(vision)
        self.pipeline.label(adapter, 1, 1, 'multimodal')
        self.assertEqual(adapter.call_body.call_args.args[0], vision['body'])

    def test_build_is_reproducible_and_seed_groups_do_not_leak(self):
        for seed in range(20):
            payload, _ = self.add(seed=seed)
            self.pipeline.complete(payload['request_id'], TEACHER, result(payload))
        vision, _ = self.add(seed=3, image='data:image/png;base64,FAKE')
        self.pipeline.complete(vision['request_id'], TEACHER, result(vision))
        # Same prompt from another seed unions the groups and deduplicates the prompt.
        first = json.loads(self.pipeline.db.execute('SELECT payload FROM inputs ORDER BY rowid LIMIT 1').fetchone()[0])
        duplicate, source = fixture(seed=999, observation=first['observation'])
        self.pipeline.add_input(duplicate, source)
        self.pipeline.complete(duplicate['request_id'], TEACHER, result(duplicate))
        a = self.pipeline.build(self.root / 'a', TEACHER)
        b = self.pipeline.build(self.root / 'b', TEACHER)
        self.assertEqual(a, b)
        manifest, data = check_dataset(self.root / 'a')
        self.assertEqual(manifest['files']['multimodal.jsonl']['rows'], 1)
        self.assertEqual(len(data['train.jsonl']) + len(data['validation.jsonl']), 20)
        self.assertTrue(data['train.jsonl']); self.assertTrue(data['validation.jsonl'])
        groups = {}
        for row in data['provenance.jsonl']:
            self.assertEqual(groups.setdefault(row['group'], row['split']), row['split'])
        with (self.root / 'a' / 'train.jsonl').open('a') as stream:
            stream.write('{}\n')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            check_dataset(self.root / 'a')

    def test_keyset_pagination_handles_server_caps(self):
        repository = Mock()
        repository.read.side_effect = [[{'sequence': 1}], [{'sequence': 2}], []]
        self.assertEqual(len(list(pages(repository, 'events', 'session_id=eq.x', 'sequence'))), 2)
        self.assertIn('sequence=gt.1', repository.read.call_args_list[1].args[1])

    def test_export_skips_legacy_and_reads_only_committed_input(self):
        payload, source = fixture()
        sid, aid = source['session_id'], uid()
        request = dict(id=payload['request_id'], policy_input_artifact_id=aid,
                       policy_input_hash=digest(payload), observation_hash=source['observation_hash'])
        event = dict(sequence=2, robot_id='W1', type='inference_requested', payload=dict(request=request))
        artifact = dict(id=aid, kind='policy_input', ready=True, sequence=3, metadata=dict(request_id=request['id']))
        repository = Mock()
        def read(table, query):
            if table == 'sessions':
                return [] if 'parent_session_id' in query else [dict(seed=7, committed_sequence=3)]
            if table == 'artifacts': return []
            self.assertIn('sequence=lte.3', query)
            if 'sequence=gt.' in query: return []
            return [dict(event, sequence=1, payload=dict(request={})), event]
        repository.read.side_effect = read
        repository.artifact_bytes.return_value = (gzip.compress(canonical(payload).encode()), artifact)
        report = self.pipeline.export_sessions(repository, [sid])
        self.assertEqual(report, dict(imported=1, legacy_skipped=1, sessions=1))
        self.assertEqual(self.pipeline.export_sessions(repository, [sid])['imported'], 0)
        artifact['sequence'] = 4
        with self.assertRaisesRegex(ValueError, 'Uncommitted'):
            self.pipeline.export_sessions(repository, [sid])

    def test_lineage_unites_worker_seeds_season_days_and_continuations(self):
        parent, child, continuation, next_day = (uid() for _ in range(4))
        records = {
            parent: dict(seed=7, metadata={'configuration': {'season_seed': 7}}),
            child: dict(seed=12, metadata={'configuration': {'parent_session_id': parent}}),
            continuation: dict(seed=12, metadata={'configuration': {'continuation_source': child}}),
            next_day: dict(seed=8, metadata={'configuration': {'season_seed': 7}}),
        }
        repository = Mock()
        repository.read.side_effect = lambda table, query: [records[query.split('id=eq.')[1].split('&')[0]]]
        cache = {}
        for sid, expected in ((parent, {'seed:7'}), (child, {'seed:7', 'seed:12'}),
                              (continuation, {'seed:7', 'seed:12'}), (next_day, {'seed:7', 'seed:8'})):
            self.assertEqual(lineage_groups(repository, sid, cache), expected)
        for seed, sid in ((7, parent), (12, child), (8, next_day)):
            payload, source = fixture(seed=seed)
            source['split_groups'] = sorted(lineage_groups(repository, sid, cache))
            self.pipeline.add_input(payload, source)
            self.pipeline.complete(payload['request_id'], TEACHER, result(payload))
        standalone, source = fixture(seed=12)
        self.pipeline.add_input(standalone, source)
        self.pipeline.complete(standalone['request_id'], TEACHER, result(standalone))
        self.pipeline.build(self.root / 'lineage', TEACHER)
        _, data = check_dataset(self.root / 'lineage')
        self.assertEqual(len({r['split'] for r in data['provenance.jsonl']}), 1)
        records[parent]['metadata']['configuration']['parent_session_id'] = child
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            lineage_groups(repository, parent, {})

    def test_teacher_validation_failure_preserves_billed_response(self):
        payload, _ = self.add()
        invalid = result(payload, dict(action='water', arguments={}))
        adapter = Mock(model=TEACHER); adapter.call_body.return_value = invalid
        self.assertEqual(self.pipeline.label(adapter, 1, 1)['stopped'], 'teacher_error')
        saved = json.loads(self.pipeline.db.execute('SELECT result FROM labels').fetchone()[0])
        self.assertEqual(saved['response']['cost'], .01)
        self.assertEqual(saved['response']['response_id'], 'fake-response')
        self.assertEqual(saved['response']['decision'], invalid['decision'])
        self.assertTrue(saved['reason'])

    def test_action_specific_required_fields_cannot_be_omitted(self):
        for action in ('scan_lidar', 'set_gripper', 'confirm_contact', 'move_arm', 'assess_alignment'):
            payload, _ = fixture(observation=dict(trial='precision', available_actions=[action], frame={'id': 'f'}))
            with self.assertRaises(ValueError):
                completion_for(payload, dict(action=action, arguments={}))

    def test_image_action_bounds_and_current_frame_are_required(self):
        payload, _ = fixture(observation=dict(trial='precision', available_actions=['set_gripper'], frame={'id': 'current'}))
        for args in (dict(opening=5, force=30), dict(opening=.1, force=30, frame_id='old')):
            with self.assertRaises(ValueError):
                completion_for(payload, dict(action='set_gripper', arguments=args))

    def test_training_masks_prompt_and_rejects_lost_tools_or_truncation(self):
        payload, _ = fixture()
        row = dict(prompt=payload['body']['messages'], tools=payload['body']['tools'],
                   completion=[completion_for(payload, result(payload)['decision'])])
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return 'prompt:' if kwargs['add_generation_prompt'] else 'prompt:fleet_action inspect'
            def __call__(self, text, **kwargs):
                return {'input_ids': list(text.encode())}
        tokenized = render_example(Tokenizer(), row, 100)
        self.assertEqual(tokenized['completion_mask'][:7], [0] * 7)
        self.assertTrue(all(tokenized['completion_mask'][7:]))
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            render_example(Tokenizer(), row, 10)
        tokenizer = Tokenizer(); tokenizer.apply_chat_template = lambda *a, **k: 'prompt:'
        with self.assertRaisesRegex(ValueError, 'does not render tool calls'):
            render_example(tokenizer, row, 100)
