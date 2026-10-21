import sys
from pathlib import Path as _StagePath
sys.path.insert(0, str(_StagePath(__file__).resolve().parents[1]))
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tools.experiment_control import ControlError, route, run_task
from tests.cd5_fixtures import configure
STATE_PATH = 'coordination/cd5/CHECKPOINT.json'
from tools.experiment_registry import read_events, query_events


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        configure(self.root)
        for rel in ['coordination/cd5/OUTLINE.md','coordination/cd5/CHECKPOINT.json','coordination/cd5/EVIDENCE.jsonl','coordination/cd5/KNOWLEDGE.jsonl','coordination/cd5/ATTENTION.jsonl','results/test/PROTOCOL.md']:
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('' if rel.endswith('jsonl') else 'test', encoding='utf-8')
        self.state = {'schema_version': 3, 'phase': 'ready', 'owner': {'role': 'hq', 'thread_id': 'p'},
                      'user_stop': {'active': False}, 'next_action': {'kind': 'execute'},
                      'memory': {'outline':'coordination/cd5/OUTLINE.md','checkpoint':'coordination/cd5/CHECKPOINT.json','evidence':'coordination/cd5/EVIDENCE.jsonl','knowledge':'coordination/cd5/KNOWLEDGE.jsonl','attention':'coordination/cd5/ATTENTION.jsonl'},
                      'active_task': {'id': 'test', 'status': 'authorized', 'command': ['fake'],
                                      'protocol_path': 'results/test/PROTOCOL.md',
                                      'protocol_sha256': hashlib.sha256(b'test').hexdigest(), 'max_attempts': 1,
                                      **{k: 'specified' for k in ['question', 'prior_evidence', 'evidence_gap',
                                                                'novelty_reason', 'acceptance_criteria']}}}
        self.save()

    def save(self):
        (self.root / STATE_PATH).write_text(json.dumps(self.state), encoding='utf-8')

    def test_cd5_off_is_independent_of_mac(self):
        self.state['cd5'] = {'enabled': False}
        self.state['mac'] = {'mode': 'auto'}
        self.save()
        self.assertEqual(route(self.state, used_percent=10, ordinary_allowed=True)['action'], 'wait_cd5_disabled')
        with self.assertRaisesRegex(ControlError, 'CD5 workflow is paused'):
            run_task(self.root, 'test', ['fake'])

    def test_user_stop_precedes_cd5_pause(self):
        self.state['cd5'] = {'enabled': False}
        self.state['user_stop']['active'] = True
        self.assertEqual(route(self.state, used_percent=10, ordinary_allowed=True)['action'], 'wait_user_stop')

    def test_stop_has_priority_even_over_missing_quota_and_old_pair(self):
        self.assertEqual(route({'user_stop': {'active': True}})['action'], 'wait_user_stop')

    def test_run_stopped_never_invokes_process(self):
        self.state['user_stop']['active'] = True
        self.state['next_action'] = {'kind': 'wait_user'}
        self.save()
        with patch('tools.experiment_control.subprocess.run') as proc:
            with self.assertRaises(ControlError):
                run_task(self.root, 'test', ['fake'])
            proc.assert_not_called()

    def test_changed_protocol_blocks(self):
        (self.root / 'results/test/PROTOCOL.md').write_text('changed')
        with self.assertRaises(ControlError):
            run_task(self.root, 'test', ['fake'])

    def test_changed_command_blocks(self):
        with self.assertRaises(ControlError):
            run_task(self.root, 'test', ['different'])

    def test_exit_zero_records_facts_not_semantic_success_and_budget_blocks_repeat(self):
        with patch('tools.experiment_control.subprocess.run', return_value=SimpleNamespace(returncode=0)) as proc:
            self.assertEqual(run_task(self.root, 'test', ['fake']), 0)
            proc.assert_called_once()
            with self.assertRaises(ControlError):
                run_task(self.root, 'test', ['fake'])
        events = read_events(self.root)
        self.assertEqual([e['event_type'] for e in events], ['protocol_frozen', 'execution_started', 'execution_completed'])
        self.assertEqual(events[-1]['machine_facts']['semantic_status'], 'not_assessed')


    def test_generic_artifact_does_not_block_admitted_executor(self):
        from tools.project_memory import append as append_memory, select as select_memory
        append_memory(self.root, 'evidence', {'id':'catalogued-source','kind':'artifact','payload':{'title':'source'},'provenance':{'source':'test'}}, 'executor')
        with patch('tools.experiment_control.subprocess.run', return_value=SimpleNamespace(returncode=0)) as proc:
            self.assertEqual(run_task(self.root, 'test', ['fake']), 0)
            proc.assert_called_once()
        self.assertEqual(len(read_events(self.root)), 3)
        self.assertEqual(select_memory(self.root,'evidence',['catalogued-source'],full=True)[0]['kind'],'artifact')

    def test_process_error_retains_attempt(self):
        with patch('tools.experiment_control.subprocess.run', side_effect=OSError('fake')):
            with self.assertRaises(ControlError):
                run_task(self.root, 'test', ['fake'])
        self.assertEqual(read_events(self.root)[-1]['event_type'], 'technical_failed')

    def test_new_experiment_is_searchable_after_state_is_cleared(self):
        self.state['active_task']['question'] = 'Does compression preserve worksheet boundaries?'
        self.save()
        with patch('tools.experiment_control.subprocess.run', return_value=SimpleNamespace(returncode=0)):
            run_task(self.root, 'test', ['fake'])
        self.state['active_task'] = None
        self.save()
        self.assertTrue(query_events(self.root, 'worksheet boundaries')['matches'])

    def test_existing_lock_blocks_duplicate(self):
        (self.root / 'coordination/cd5/.execution.lock').write_text('other')
        with self.assertRaises(ControlError):
            run_task(self.root, 'test', ['fake'])

    def test_router_waits_for_executor(self):
        self.assertEqual(route(self.state, executor_status='running', used_percent=5,
                               ordinary_allowed=True)['action'], 'wait_active')

    def test_unknown_quota_is_not_permission(self):
        self.assertEqual(route(self.state)['action'], 'quota_unknown')

    def test_unknown_executor_status_is_not_permission(self):
        self.assertEqual(route(self.state, executor_status='unknown', used_percent=10,
                               ordinary_allowed=True)['action'], 'inspect_status')

    def test_unknown_planner_status_is_not_permission(self):
        self.assertEqual(route(self.state, planner_status='unknown', used_percent=10,
                               ordinary_allowed=True)['action'], 'inspect_status')

    def test_control_only_self_active_does_not_block_reset(self):
        self.assertEqual(route(self.state, planner_status='active', control_only=True,
                               used_percent=10, ordinary_allowed=True)['action'], 'planner_decision')

    def test_control_only_never_ignores_unknown_or_active_executor(self):
        for executor, expected in [('unknown', 'inspect_status'), ('running', 'wait_active')]:
            self.assertEqual(route(self.state, planner_status='active', control_only=True,
                                   executor_status=executor, used_percent=10,
                                   ordinary_allowed=True)['action'], expected)

    def test_quota_boundary_below_threshold_allows_routing(self):
        self.assertEqual(route(self.state, used_percent=89.99, ordinary_allowed=True)['action'],
                         'planner_decision')

    def test_quota_boundary_at_and_above_threshold_waits(self):
        for used in (90, 90.01):
            with self.subTest(used=used):
                self.assertEqual(route(self.state, used_percent=used, ordinary_allowed=True)['action'],
                                 'wait_quota')

    def test_active_executor_and_user_stop_keep_priority_below_quota_threshold(self):
        self.assertEqual(route(self.state, executor_status='running', used_percent=89.99,
                               ordinary_allowed=True)['action'], 'wait_active')
        self.assertEqual(route({'user_stop': {'active': True}}, used_percent=90,
                               ordinary_allowed=True)['action'], 'wait_user_stop')


if __name__ == '__main__':
    unittest.main()
