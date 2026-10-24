import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import cu_archive as ca


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.cu-test-', dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'coordination/cd5'
        self.base.mkdir(parents=True)
        self.active = self.base / 'EVIDENCE.jsonl'
        self.rows = [dict(schema_version=1, id=f'e{i}', kind='artifact',
                          provenance={'source': 'test'},
                          payload={'type': 'control_unit_event', 'n': i}) for i in range(8)]
        self.write(self.rows)

    def write(self, rows):
        self.active.write_bytes(ca._bytes(rows))

    def test_dryrun_does_not_write_and_alltime_lookup_stable(self):
        before = self.active.read_bytes()
        result = ca.archive_evidence(self.root, keep_records=2)
        self.assertFalse(result['applied'])
        self.assertEqual(self.active.read_bytes(), before)
        self.assertFalse((self.base / 'archive').exists())
        result = ca.archive_evidence(self.root, keep_records=2, apply=True)
        self.assertEqual(result['archived'], 6)
        self.assertEqual(ca.evidence_rows(self.root), self.rows)
        self.assertEqual(json.loads(self.active.read_text().splitlines()[0])['id'], 'e6')
        self.assertEqual(ca.archive_evidence(self.root, keep_records=2, apply=True)['archived'], 0)

    def test_cu_only_preserves_unrelated_and_unsupported(self):
        other = dict(self.rows[0], id='other', payload={'type': 'science'})
        legacy = {'id': 'legacy', 'text': 'preserve'}
        self.write([other, legacy] + self.rows)
        result = ca.archive_evidence(self.root, keep_records=1, cu_only=True, apply=True)
        self.assertEqual(ca._pm()._jsonl(self.active), [other, legacy, self.rows[-1]])
        self.assertEqual(result['unsupported_records'], ['legacy'])

    def test_size_bound_and_invalid_limits(self):
        limit = len(ca._bytes([self.rows[-1]]))
        result = ca.archive_evidence(self.root, max_bytes=limit, apply=True)
        self.assertLessEqual(result['eligible_after']['bytes'], limit)
        self.assertLessEqual(self.active.stat().st_size, limit)
        for value in [-1, True, 1.2]:
            with self.assertRaises(ValueError):
                ca.archive_evidence(self.root, max_bytes=value)

    def test_interrupted_move_recovers_identical_duplicates(self):
        real_atomic = ca._pm()._atomic
        def fail_hot(path, data):
            if path == self.active:
                raise OSError('simulated crash')
            return real_atomic(path, data)
        with patch.object(ca._pm(), '_atomic', side_effect=fail_hot):
            with self.assertRaises(OSError):
                ca.archive_evidence(self.root, keep_records=2, apply=True)
        self.assertEqual(ca.evidence_rows(self.root), self.rows)
        ca.archive_evidence(self.root, keep_records=2, apply=True)
        self.assertEqual(ca.evidence_rows(self.root), self.rows)
        self.assertEqual(len(list((self.base / 'archive').rglob('*.jsonl'))), 1)

    def test_conflicting_duplicate_refuses_write(self):
        directory = self.base / 'archive/evidence-store'
        directory.mkdir(parents=True)
        (directory / 'conflict.jsonl').write_bytes(ca._bytes([dict(self.rows[0], payload={})]))
        before = self.active.read_bytes()
        with self.assertRaises(ValueError):
            ca.archive_evidence(self.root, keep_records=0, apply=True)
        self.assertEqual(before, self.active.read_bytes())

    def test_budget_reports_all_five_and_overrides(self):
        settings = self.root / '.cd5'
        settings.mkdir()
        (settings / 'config.json').write_text(json.dumps({'memory_limits_bytes': {'EVIDENCE.jsonl': 1}}))
        result = ca.memory_budget(self.root)
        self.assertEqual(len(result['files']), 5)
        self.assertTrue(result['files']['EVIDENCE.jsonl']['over_limit'])
        self.assertTrue(result['action_needed'])

    def test_multiple_batches_keep_order_and_detect_corruption(self):
        ca.archive_evidence(self.root,keep_records=6,apply=True)
        ca.archive_evidence(self.root,keep_records=4,apply=True)
        ca.archive_evidence(self.root,keep_records=2,apply=True)
        self.assertEqual(ca.evidence_rows(self.root),self.rows)
        first=sorted((self.base/'archive/evidence-store').glob('*.jsonl'))[0]
        first.write_bytes(first.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            ca.evidence_rows(self.root)

    def test_full_archive_preserves_scientific_registry(self):
        from tools import experiment_registry as registry
        event=registry.build_event('fixture-note','note',root=self.root,provenance={'source':'fixture'},machine_facts={'fixture':True})
        registry.append_event(self.root,event)
        before=registry.read_events(self.root)
        ca.archive_evidence(self.root,keep_records=0,max_bytes=0,apply=True)
        self.assertEqual(registry.read_events(self.root),before)

    def test_mixed_cu_and_full_archive_keeps_global_order(self):
        earlier=dict(self.rows[0],id='earlier',payload={'type':'other'})
        self.write([earlier,self.rows[1]])
        ca.archive_evidence(self.root,keep_records=0,cu_only=True,apply=True)
        ca.archive_evidence(self.root,keep_records=0,apply=True)
        self.assertEqual([r['id'] for r in ca.evidence_rows(self.root)],['earlier','e1'])


if __name__ == '__main__':
    unittest.main()
