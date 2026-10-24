import json
from pathlib import Path
import tempfile
import unittest

from tools import cu_auto_telemetry as auto
from tools.work_units import annotate_report
from tests.test_cu_auto_telemetry import snapshot, turn


class ObservedUsageTests(unittest.TestCase):
    def measure(self, rows, notes=()):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'native.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in [
                {'type': 'session_meta', 'payload': {'id': 'owner'}}, *rows]) + '\n')
            session = auto._read(path)
            return auto._measure(session, set(range(len(session['turns']))), {'role': 'hq'}, notes)

    def test_open_turn_retains_verified_counter_delta_and_missing_duration(self):
        person = self.measure([snapshot(100, 0), *turn('one', 5, complete=False)])
        self.assertEqual(person['coverage'], 'partial')
        self.assertEqual(person['usage'], {'cached_input': 20, 'uncached_input': 20, 'output': 4})
        self.assertIsNone(person['elapsed_ms'])
        self.assertIn('pending_turn', person['telemetry_diagnostics'])
        self.assertIsNotNone(person['telemetry_provenance']['observed_through'])
        person['exclusive_scope'] = True
        priced = annotate_report({'units': [{'cu_id': 'CU1', 'usage_status': 'partial', 'participants': [person]}]})
        cost = priced['units'][0]['work_units']
        self.assertEqual(cost['status'], 'partial')
        self.assertIsNotNone(cost['known_value'])
        self.assertIsNone(cost['value'])

    def test_completed_prefix_and_pending_tail_have_one_observed_delta(self):
        person = self.measure([snapshot(100, 0), *turn('one', 5), *turn('two', 15, ending=180, complete=False)])
        self.assertEqual(person['usage'], {'cached_input': 40, 'uncached_input': 40, 'output': 8})
        self.assertEqual(person['coverage'], 'partial')

    def test_pending_does_not_hide_unsafe_counters(self):
        rows = [snapshot(100, 0), *turn('one', 5, complete=False)]
        for notes in [('ambiguous_turn_claim',), ('ambiguous_parent_turn_claim',)]:
            person = self.measure(rows, notes)
            self.assertTrue(all(value is None for value in person['usage'].values()))
        for invalid in ([snapshot(200, 0), *turn('one', 5, complete=False)], turn('one', 5, complete=False)):
            person = self.measure(invalid)
            self.assertTrue(all(value is None for value in person['usage'].values()))


if __name__ == '__main__':
    unittest.main()
