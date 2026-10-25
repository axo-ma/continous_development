"""Synthetic supervisor fixtures; never inspect real journals or start a model."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import planner_control as pc


class PlannerControlTests(unittest.TestCase):
    def setUp(self):
        self.s = {'schema_version': 1, 'state': 'READY', 'owner_thread_id': 'synthetic',
                  'next_action': 'review saved result', 'authorized': True}
        self.cp = {'owner': {'thread_id': 'synthetic'}, 'user_stop': {'active': False},
                   'goal_status': 'open'}
        self.obs = {'observed_at': 1000, 'owner_thread_id': 'synthetic',
                    'planner_status': 'idle', 'workers_idle': True,
                    'quota': {'ordinary_allowed': True, 'used_percent': 30, 'window_minutes': 300}}

    def decision(self, **state):
        return pc.decide({**self.s, **state}, self.cp, self.obs, 1000)[0]

    def test_gates_and_reset(self):
        self.assertEqual(self.decision(), 'wake')
        for state in ('STOP', 'WAIT_USER', 'COMPLETE', 'BLOCKED', 'DISPATCHING'):
            self.assertEqual(self.decision(state=state), 'hold')
        self.assertEqual(self.decision(state='WAIT_QUOTA', resume_after=1001), 'hold')
        self.assertEqual(self.decision(state='WAIT_QUOTA', resume_after=999), 'wake')
        self.assertEqual(self.decision(authorized=False), 'hold')
        self.cp['user_stop']['active'] = True
        self.assertEqual(self.decision(), 'hold')

    def test_unknown_busy_stale_or_wrong_quota(self):
        for changes in ({'planner_status': 'active'}, {'workers_idle': None},
                        {'observed_at': 939}, {'owner_thread_id': 'other'},
                        {'quota': {'ordinary_allowed': True, 'used_percent': 1, 'window_minutes': 10080}},
                        {'quota': {'ordinary_allowed': True, 'used_percent': float('nan'), 'window_minutes': 300}}):
            self.assertEqual(pc.decide(self.s, self.cp, {**self.obs, **changes}, 1000)[0], 'hold')
        self.cp['owner']['thread_id'] = 'new-owner'
        self.assertEqual(self.decision(), 'hold')

    def test_single_crash_recovery(self):
        self.assertEqual(self.decision(state='RUNNING', heartbeat_at=900), 'hold')
        self.assertEqual(self.decision(state='RUNNING', heartbeat_at=1), 'wake')
        self.assertEqual(self.decision(state='RUNNING', heartbeat_at=1, recovery_attempts=1), 'block')

    def project(self, root, state='READY', **extra):
        directory = root / 'coordination/cd5'
        directory.mkdir(parents=True)
        pc.atomic(directory / 'CHECKPOINT.json', self.cp)
        fields = {k: v for k, v in self.s.items() if k not in {'state', 'schema_version'}}
        pc.save(directory, {}, state, 'synthetic init', 'user', 1, **{**fields, **extra})
        return directory

    def test_no_adapter_calls_during_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.project(root, 'WAIT_QUOTA', resume_after=2000)
            with patch.object(pc, 'adapter_call') as host:
                self.assertEqual(pc.tick(root, ['unused'], 1000)['action'], 'hold')
                host.assert_not_called()

    def test_dispatch_once_and_reboot_no_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = self.project(root)
            calls = []
            def host(argv, request):
                calls.append(request['operation'])
                if request['operation'] == 'probe':
                    return self.obs
                return {'accepted': True, 'dispatch_id': request['dispatch_id']}
            with patch.object(pc, 'adapter_call', side_effect=host):
                self.assertEqual(pc.tick(root, ['unused'], 1000)['action'], 'woke')
                self.assertEqual(pc.tick(root, ['unused'], 1001)['action'], 'hold')
            self.assertEqual(calls.count('wake'), 1)
            self.assertEqual(pc.load(directory)['state'], 'RUNNING')

    def test_ambiguous_delivery_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = self.project(root)
            with patch.object(pc, 'adapter_call', side_effect=[self.obs, TimeoutError('synthetic')]):
                with self.assertRaises(TimeoutError):
                    pc.tick(root, ['unused'], 1000)
            self.assertEqual(pc.load(directory)['state'], 'DISPATCHING')
            with patch.object(pc, 'adapter_call') as host:
                pc.tick(root, ['unused'], 2000)
                host.assert_not_called()

    def test_journal_commit_failure_blocks_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = self.project(root)
            old = pc.load(directory)
            with patch.object(pc, 'atomic', side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError):
                    pc.save(directory, old, 'DISPATCHING', 'reserve wake', 'watchdog')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                pc.load(directory)

    def test_missing_and_corrupt_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                pc.tick(root, now=1000)
            directory = root / 'coordination/cd5'
            (directory / 'PLANNER_STATE.json').write_text('{broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                pc.tick(root, now=1000)

    def test_stop_changed_after_probe_prevents_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = self.project(root)
            def host(argv, request):
                self.cp['user_stop']['active'] = True
                pc.atomic(directory / 'CHECKPOINT.json', self.cp)
                return self.obs
            with patch.object(pc, 'adapter_call', side_effect=host) as call:
                self.assertEqual(pc.tick(root, ['unused'], 1000)['action'], 'hold')
                self.assertEqual(call.call_count, 1)

    def test_checkpoint_lifecycle_sync_and_stop_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = self.project(root)
            self.cp['planner_control'] = {'state': 'WAIT_QUOTA', 'reason': 'quota boundary',
                                          'authorized': True, 'reset_at': 2000}
            self.cp['next_action'] = {'kind': 'review_saved_result'}
            pc.atomic(directory / 'CHECKPOINT.json', self.cp)
            pc.sync_checkpoint(root, self.cp)
            state = pc.load(directory)
            self.assertEqual(state['state'], 'WAIT_QUOTA')
            self.assertEqual(state['resume_after'], 2060)
            changed = {**self.cp, 'revision': 2}
            self.assertEqual(pc.decide(state, changed, self.obs, 3000)[0], 'hold')
            self.cp['user_stop']['active'] = True
            pc.sync_checkpoint(root, self.cp)
            self.assertEqual(pc.load(directory)['state'], 'STOP')

    def test_missing_lifecycle_record_blocks_opted_in_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = self.project(root)
            pc.sync_checkpoint(root, self.cp)
            self.assertEqual(pc.load(directory)['state'], 'BLOCKED')

    def test_readonly_host_cannot_dispatch(self):
        self.obs['wake_supported'] = False
        self.assertEqual(self.decision(), 'hold')

    def test_reconcile_after_interrupted_commit_never_rearms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = self.project(root)
            old = pc.load(directory)
            with patch.object(pc, 'atomic', side_effect=OSError('synthetic')):
                with self.assertRaises(OSError):
                    pc.save(directory, old, 'DISPATCHING', 'reserved', 'watchdog')
            pc.main(['--root', str(root), 'reconcile'])
            self.assertEqual(pc.load(directory)['state'], 'BLOCKED')
            self.assertFalse(pc.load(directory)['authorized'])


if __name__ == '__main__':
    unittest.main()
