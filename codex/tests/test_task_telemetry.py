import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import task_telemetry as telemetry


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=ROOT, prefix='.telemetry-test-'))
        self.addCleanup(lambda: shutil.rmtree(self.tmp))

    def mapping(self, totals=(100, 150, 150, 210), child=False):
        meta = {'id': 'child' if child else 'owner'}
        if child:
            meta.update(parent_thread_id='owner', source={'subagent': {'thread_spawn': {'parent_thread_id': 'owner'}}})
        rows = [{'type': 'session_meta', 'ordinal': 0, 'payload': meta},
                {'type': 'turn_context', 'ordinal': 1, 'payload': {'model': 'example', 'effort': 'high', 'turn_id': 'turn'}}]
        for ordinal, n in enumerate(totals, 2):
            usage = {'input_tokens': n, 'cached_input_tokens': n // 2,
                     'output_tokens': n // 10, 'reasoning_output_tokens': n // 20}
            rows.append({'ordinal': ordinal, 'type': 'event_msg', 'payload': {'type': 'token_count',
                         'info': {'total_token_usage': usage, 'last_token_usage': usage, 'model_context_window': 1000}}})
        path = self.tmp / 'rollout.jsonl'
        path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
        return {'task_id': 'task-a', 'owner_thread_id': 'owner', 'participants': [
            {'thread_id': meta['id'], 'source_file': str(path), 'role': 'helper' if child else 'hq',
             'baseline_ordinal': 2, 'end_ordinal': 5}]}

    def test_cumulative_delta_repeated_snapshot_not_summed(self):
        result = telemetry.collect(self.mapping())
        actor = result['participants'][0]
        self.assertEqual(actor['usage']['input'], 110)
        self.assertEqual(actor['usage']['uncached_input'], 55)
        self.assertIsNone(result['team_total'])
        self.assertIsNone(actor['request_count'])
        self.assertIsNone(actor['active_ms'])
        self.assertEqual(actor['context_observations'][-1]['reported_last_request_input'], 210)

    def test_counter_reset_is_unknown(self):
        result = telemetry.collect(self.mapping((100, 150, 5, 30)))
        self.assertTrue(result['participants'][0]['counter_reset'])
        self.assertIsNone(result['participants'][0]['usage']['input'])

    def test_missing_exact_baseline_is_unknown(self):
        mapping = self.mapping()
        mapping['participants'][0]['baseline_ordinal'] = 1
        self.assertEqual(telemetry.collect(mapping)['participants'][0]['coverage'], 'partial')

    def test_child_identity_must_verify(self):
        mapping = self.mapping(child=True)
        self.assertEqual(telemetry.collect(mapping)['participants'][0]['thread_id'], 'child')
        mapping['owner_thread_id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'parent'):
            telemetry.collect(mapping)

    def test_duplicate_participant_rejected(self):
        mapping = self.mapping()
        mapping['participants'] *= 2
        with self.assertRaises(ValueError):
            telemetry.collect(mapping)

    def nested_mapping(self):
        mapping = self.mapping(child=True)
        main = mapping['participants'][0]
        main['role'] = 'executor'
        main_path = Path(main['source_file'])
        main_path.replace(self.tmp / 'executor.jsonl')
        main['source_file'] = str(self.tmp / 'executor.jsonl')
        rows = [json.loads(line) for line in Path(main['source_file']).read_text().splitlines()]
        rows[0]['payload'] = {'id': 'helper', 'parent_thread_id': 'child',
            'source': {'subagent': {'thread_spawn': {'parent_thread_id': 'child'}}}}
        helper_path = self.tmp / 'helper.jsonl'
        helper_path.write_text('\n'.join(json.dumps(r) for r in rows))
        mapping['participants'].append({**main, 'thread_id': 'helper', 'role': 'helper',
            'parent_thread_id': 'child', 'source_file': str(helper_path)})
        return mapping

    def test_nested_helper_verified_and_visible(self):
        result = telemetry.collect(self.nested_mapping())
        self.assertEqual(result['participants'][1]['parent_thread_id'], 'child')
        self.assertEqual(result['participants'][1]['usage']['input'], 110)
        self.assertIsNone(result['team_total'])

    def test_helper_cannot_parent_or_create_main_role(self):
        mapping = self.nested_mapping()
        mapping['participants'][0]['role'] = 'helper'
        with self.assertRaisesRegex(ValueError, 'main role'):
            telemetry.collect(mapping)
        mapping = self.nested_mapping()
        mapping['participants'][1]['role'] = 'reviewer'
        with self.assertRaisesRegex(ValueError, 'main role'):
            telemetry.collect(mapping)

    def test_nested_helper_missing_parent_rejected(self):
        mapping = self.nested_mapping()
        mapping['participants'] = mapping['participants'][1:]
        with self.assertRaises(ValueError):
            telemetry.collect(mapping)

    def test_appending_outside_interval_keeps_identity(self):
        mapping = self.mapping()
        before = telemetry.collect(mapping)
        with Path(mapping['participants'][0]['source_file']).open('a', encoding='utf-8') as stream:
            stream.write('\n' + json.dumps({'ordinal': 6, 'type': 'event_msg', 'payload': {}}))
        self.assertEqual(before, telemetry.collect(mapping))

    def test_impossible_delta_is_unknown(self):
        mapping = self.mapping()
        path = Path(mapping['participants'][0]['source_file'])
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows[2:]:
            usage = row['payload']['info']['total_token_usage']
            usage['cached_input_tokens'] = 0 if row['ordinal'] == 2 else 180
            usage['input_tokens'] = 200 if row['ordinal'] == 2 else 220
        path.write_text('\n'.join(json.dumps(r) for r in rows))
        actor = telemetry.collect(mapping)['participants'][0]
        self.assertTrue(actor['inconsistent_delta'])
        self.assertIsNone(actor['usage']['uncached_input'])


if __name__ == '__main__':
    unittest.main()
