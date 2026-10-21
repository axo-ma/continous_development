import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import cu_auto_telemetry as auto


def stamp(seconds):
    return f'2026-10-21T12:{seconds // 60:02d}:{seconds % 60:02d}+00:00'


def event(kind, seconds, **payload):
    return {'type': 'event_msg', 'timestamp': stamp(seconds), 'payload': {'type': kind, **payload}}


def snapshot(value, seconds):
    return event('token_count', seconds, info={'total_token_usage': {
        'input_tokens': value, 'cached_input_tokens': value // 2, 'output_tokens': value // 10}})


def turn(identity, start, ending=140, complete=True, model='gpt-6.1-sol'):
    rows = [event('task_started', start, turn_id=identity),
            {'type': 'turn_context', 'timestamp': stamp(start + 1), 'payload': {'turn_id': identity, 'model': model, 'effort': 'low'}},
            snapshot(ending, start + 2)]
    if complete:
        rows.append(event('task_complete', start + 4, turn_id=identity, duration_ms=4000))
    return rows


class AutoTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.root = Path(self.temp.name)
        (self.root / '.cd5').mkdir()
        (self.root / 'sessions').mkdir()
        (self.root / '.cd5/config.json').write_text(json.dumps({'control_units': {'telemetry': {
            'session_roots': ['sessions']}}}), encoding='utf-8')
        (self.root / 'CHECKPOINT.json').write_text('{"STOP":true,"owner":{"thread_id":"hq"}}', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def session(self, identity='hq', rows=(), parent=None, verified=True, created=0):
        meta = {'id': identity, 'session_id': 'wrong-alias', 'timestamp': stamp(created)}
        if parent:
            meta['parent_thread_id'] = parent
            if verified:
                meta['source'] = {'subagent': {'thread_spawn': {'parent_thread_id': parent}}}
        path = self.root / 'sessions' / (identity + '.jsonl')
        self.write(path, [{'type': 'session_meta', 'payload': meta}, *rows])
        return path

    def write(self, path, rows):
        path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf-8')

    def anchor(self, path, turn_id):
        session = auto._read(path)
        selected = next(t for t in session['turns'] if t['id'] == turn_id)
        return {'schema_version': 1, 'thread_id': session['meta']['id'], 'turn_id': turn_id,
                'source_file': str(path.resolve()), 'start_position': selected['start']['_position'],
                'start_sha256': selected['start']['_sha256'], 'prefix_sha256': selected['start']['_prefix_sha256'], 'recorded_at': stamp(1)}

    def cu_event(self, cu='cu', action='open', anchor=None, caller='hq', **payload):
        p = {'type': 'control_unit_event', 'cu_id': cu, 'action': action, **payload}
        if anchor:
            p['auto_anchor'] = anchor
        return {'id': f'{cu}-{action}', 'payload': p, 'provenance': {'caller_thread_id': caller}}

    def data(self, *identities):
        return {'units': [{'cu_id': identity, 'participants': [], 'usage': dict.fromkeys(auto.FIELDS),
                           'usage_status': 'unknown', 'reported_ms': None} for identity in identities or ('cu',)]}

    def bounded(self, path, first='one', last='one', cu='cu'):
        return [self.cu_event(cu=cu, anchor=self.anchor(path, first)),
                self.cu_event(cu=cu, action='status', status='completed', anchor=self.anchor(path, last))]

    def test_capture_only_observed_active_turn_and_meta_id(self):
        path = self.session(rows=[snapshot(100, 0), *turn('one', 5, complete=False)])
        anchor = auto.capture_anchor(self.root, 'hq')
        self.assertEqual(anchor['turn_id'], 'one')
        self.assertEqual(anchor['start_position'], 3)
        self.assertEqual(anchor['start_sha256'], self.anchor(path, 'one')['start_sha256'])
        self.assertIsNone(auto.capture_anchor(self.root, 'wrong-alias'))
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event('task_complete', 9, turn_id='one', duration_ms=4000)) + '\n')
        self.assertIsNone(auto.capture_anchor(self.root, 'hq'))

    def test_repeated_reads_are_exact_readonly_and_closing_turn_is_full(self):
        path = self.session(rows=[snapshot(100, 0), *turn('one', 5), snapshot(140, 10)])
        source = self.data(); original = copy.deepcopy(source)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        events = self.bounded(path)
        result = auto.enrich_report(self.root, source, events)
        self.assertEqual(result, auto.enrich_report(self.root, source, events))
        unit = result['units'][0]
        self.assertEqual(unit['usage'], {'cached_input': 20, 'uncached_input': 20, 'output': 4})
        self.assertEqual(unit['usage_status'], 'complete')
        self.assertEqual(unit['reported_ms'], 4000)
        self.assertTrue(unit['participants'][0]['exclusive_scope'])
        self.assertEqual(source, original)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_pending_tail_becomes_complete_after_append(self):
        path = self.session(rows=[snapshot(100, 0), *turn('one', 5, complete=False)])
        events = self.bounded(path)
        pending = auto.enrich_report(self.root, self.data(), events)['units'][0]
        self.assertEqual(pending['usage_status'], 'partial')
        self.assertIsNone(pending['usage']['output'])
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event('task_complete', 9, turn_id='one', duration_ms=4000)) + '\n')
        complete = auto.enrich_report(self.root, self.data(), events)['units'][0]
        self.assertEqual(complete['usage_status'], 'complete')

    def test_missing_baseline_reset_and_mixed_models_never_zero(self):
        cases = [turn('one', 5), [snapshot(200, 0), *turn('one', 5)],
                 [snapshot(100, 0), *turn('one', 5, complete=False),
                  {'type': 'turn_context', 'payload': {'model': 'gpt-6-luna'}},
                  event('task_complete', 9, turn_id='one', duration_ms=4000)]]
        for rows in cases:
            with self.subTest(rows=rows):
                path = self.session(rows=rows)
                unit = auto.enrich_report(self.root, self.data(), self.bounded(path))['units'][0]
                self.assertEqual(unit['usage_status'], 'partial')
                self.assertTrue(all(value is None for value in unit['usage'].values()))

    def test_conflict_detected_outside_selected_report_and_owner_verified(self):
        path = self.session(rows=[snapshot(100, 0), *turn('one', 5)])
        events = self.bounded(path, cu='a') + self.bounded(path, cu='b')
        unit = auto.enrich_report(self.root, self.data('a'), events)['units'][0]
        self.assertEqual(unit['usage_status'], 'partial')
        self.assertIn('ambiguous_turn_claim', unit['participants'][0]['telemetry_diagnostics'])
        events = self.bounded(path)
        events[0]['provenance']['caller_thread_id'] = 'imposter'
        unit = auto.enrich_report(self.root, self.data(), events)['units'][0]
        self.assertEqual(unit['usage_status'], 'unknown')

    def test_pause_excludes_intervening_turns(self):
        path = self.session(rows=[snapshot(100, 0), *turn('one', 5, 140), *turn('paused', 15, 200), *turn('resume', 25, 240)])
        events = [self.cu_event(anchor=self.anchor(path, 'one')),
                  self.cu_event(action='status', status='paused', anchor=self.anchor(path, 'one')),
                  self.cu_event(action='status', status='open', anchor=self.anchor(path, 'resume')),
                  self.cu_event(action='status', status='completed', anchor=self.anchor(path, 'resume'))]
        unit = auto.enrich_report(self.root, self.data(), events)['units'][0]
        self.assertEqual(unit['usage'], {'cached_input': 40, 'uncached_input': 40, 'output': 8})
        self.assertEqual(unit['reported_ms'], 8000)

    def child_fixture(self, registered=True):
        hq = self.session(rows=[snapshot(100, 0), *turn('one', 5)])
        child_rows = [snapshot(0, 5), *turn('child-one', 6, 20)]
        child_rows[-1]['timestamp'] = stamp(8)
        child_rows[-1]['payload']['duration_ms'] = 2000
        self.session('child', rows=child_rows, parent='hq', created=6)
        events = self.bounded(hq)
        if registered:
            events.append(self.cu_event(action='participant', participant={'thread_id': 'child', 'parent_thread_id': 'hq', 'role': 'helper', 'name': 'Помощник'}))
        return events

    def test_child_unknown_scope_and_reuse_do_not_form_full_cost(self):
        events = self.child_fixture()
        unit = auto.enrich_report(self.root, self.data(), events)['units'][0]
        self.assertEqual(unit['usage_status'], 'partial')
        self.assertFalse(any(p['exclusive_scope'] for p in unit['participants']))
        self.assertIn('parent_child_scope_not_verified', unit['telemetry_diagnostics'])
        events.append(self.cu_event(cu='other', action='participant', participant={'thread_id': 'child', 'role': 'helper'}))
        child = next(p for p in auto.enrich_report(self.root, self.data(), events)['units'][0]['participants'] if p['participant_id'] == 'child')
        self.assertIn('child_reused_across_control_units', child['telemetry_diagnostics'])

    def test_unregistered_child_keeps_measured_counters_with_unknown_role(self):
        events = self.child_fixture(registered=False)
        child = next(p for p in auto.enrich_report(self.root, self.data(), events)['units'][0]['participants'] if p['participant_id'] == 'child')
        self.assertEqual(child['role'], 'роль не указана')
        self.assertEqual(child['coverage'], 'complete')
        self.assertEqual(child['usage'], {'cached_input': 10, 'uncached_input': 10, 'output': 2})
        self.assertIn('unregistered_discovered_child', child['telemetry_diagnostics'])

    def test_independent_scope_witness_validated_once(self):
        events = self.child_fixture()
        settings = {'session_roots': ['sessions'], 'independent_scope_evidence': 'scope-proof'}
        with patch.object(auto, '_settings', return_value=settings), patch.object(auto.pm, 'select', return_value=[{'id': 'scope-proof'}]) as select:
            unit = auto.enrich_report(self.root, self.data(), events)['units'][0]
        select.assert_called_once_with(self.root, 'evidence', ['scope-proof'], full=True)
        self.assertEqual(unit['usage_status'], 'complete')
        self.assertEqual(unit['usage'], {'cached_input': 30, 'uncached_input': 30, 'output': 6})
        self.assertTrue(all(p['exclusive_scope'] for p in unit['participants']))

    def test_historical_no_anchor_disabled_and_manual_skip(self):
        with patch.object(auto, '_index', side_effect=AssertionError('must not scan')):
            self.assertEqual(auto.enrich_report(self.root, self.data(), [self.cu_event(historical=True)]), self.data())
            with patch.object(auto, '_settings', return_value={'enabled': False}):
                self.assertIsNone(auto.capture_anchor(self.root, 'hq'))
        path = self.session(rows=[snapshot(100, 0), *turn('one', 5)])
        events = self.bounded(path) + [self.cu_event(action='measurement')]
        self.assertEqual(auto.enrich_report(self.root, self.data(), events), self.data())

    def test_capture_malformed_sources_failsoft(self):
        for content in ['[]\n', '{"type":"session_meta","payload":null}\n', 'not-json\n']:
            (self.root / 'sessions/hq.jsonl').write_text(content, encoding='utf-8')
            self.assertIsNone(auto.capture_anchor(self.root, 'hq'))
        self.session(rows=[snapshot(100, 0), *turn('one', 5, complete=False)])
        with (self.root / 'sessions/hq.jsonl').open('a', encoding='utf-8') as handle:
            handle.write('[]\n')
        self.assertIsNone(auto.capture_anchor(self.root, 'hq'))

    def test_prefix_mutation_invalidates_anchor_and_unrelated_bodies_not_read(self):
        path = self.session(rows=[snapshot(100, 0), *turn('one', 5)])
        unrelated = self.session('unrelated', rows=[snapshot(0, 0), *turn('elsewhere', 5)])
        events = self.bounded(path)
        read = auto._read
        seen = []
        def guarded(source):
            seen.append(source)
            self.assertNotEqual(source, unrelated)
            return read(source)
        with patch.object(auto, '_read', side_effect=guarded):
            self.assertEqual(auto.enrich_report(self.root, self.data(), events)['units'][0]['usage_status'], 'complete')
        self.assertEqual(seen, [path])
        text = path.read_text(encoding='utf-8').replace('"input_tokens": 100', '"input_tokens": 120')
        path.write_text(text, encoding='utf-8')
        self.assertEqual(auto.enrich_report(self.root, self.data(), events)['units'][0]['usage_status'], 'unknown')

    def test_ambiguous_parent_invalidates_children_even_with_scope_proof(self):
        events = self.child_fixture(registered=False)
        path = self.root / 'sessions/hq.jsonl'
        events.extend(self.bounded(path, cu='other'))
        settings = {'session_roots': ['sessions'], 'independent_scope_evidence': 'scope-proof'}
        with patch.object(auto, '_settings', return_value=settings), patch.object(auto.pm, 'select', return_value=[{}]):
            unit = auto.enrich_report(self.root, self.data(), events)['units'][0]
        child = next(p for p in unit['participants'] if p['participant_id'] == 'child')
        self.assertIn('ambiguous_parent_turn_claim', child['telemetry_diagnostics'])
        self.assertIsNone(child['usage']['output'])

    def test_nested_helper_is_included_and_scope_stays_explicit(self):
        hq_rows = [snapshot(100, 0), *turn('one', 5)]
        hq_rows[-1]['timestamp'] = stamp(60)
        hq = self.session(rows=hq_rows)
        child_rows = [snapshot(0, 5), *turn('child-one', 10, 20)]
        child_rows[-1]['timestamp'] = stamp(50)
        self.session('child', rows=child_rows, parent='hq', created=6)
        self.session('nested', rows=[snapshot(0, 10), *turn('nested-one', 12, 10)], parent='child', created=11)
        events = self.bounded(hq)
        partial = auto.enrich_report(self.root, self.data(), events)['units'][0]
        self.assertEqual({p['participant_id'] for p in partial['participants']}, {'hq', 'child', 'nested'})
        self.assertEqual(partial['usage_status'], 'partial')
        settings = {'session_roots': ['sessions'], 'independent_scope_evidence': 'scope-proof'}
        with patch.object(auto, '_settings', return_value=settings), patch.object(auto.pm, 'select', return_value=[{}]):
            complete = auto.enrich_report(self.root, self.data(), events)['units'][0]
        self.assertEqual(complete['usage_status'], 'complete')
        self.assertEqual(complete['usage']['output'], 7)

    def test_fresh_first_snapshot_total_equals_last_is_witnessed_baseline(self):
        for same in (True, False):
            with self.subTest(same=same):
                rows = turn('one', 5)
                info = rows[2]['payload']['info']
                info['last_token_usage'] = dict(info['total_token_usage'])
                if not same:
                    info['last_token_usage']['input_tokens'] -= 1
                path = self.session(rows=rows)
                unit = auto.enrich_report(self.root, self.data(), self.bounded(path))['units'][0]
                if same:
                    self.assertEqual(unit['usage_status'], 'complete')
                    self.assertEqual(unit['usage'], {'cached_input': 70, 'uncached_input': 70, 'output': 14})
                    witness = unit['participants'][0]['telemetry_provenance']['turns'][0]
                    self.assertEqual(witness['baseline_kind'], 'initial_baseline_from_total_equals_last')
                else:
                    self.assertEqual(unit['usage_status'], 'partial')
                    self.assertIsNone(unit['usage']['output'])


if __name__ == '__main__':
    unittest.main()
