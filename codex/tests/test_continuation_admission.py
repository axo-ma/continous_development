"""Synthetic admission fixtures, not proof of Desktop coverage."""
import copy
import unittest
from tools import continuation_admission as gate
from tools import worker_observations as workers


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.cp = dict(owner={'thread_id': 'root'}, owner_generation=1,
            user_stop={'active': False}, cd5={'enabled': True}, waiting_user=False,
            goal_complete=False, continuation_authorized=True,
            next_action={'kind': 'review'}, native_goal={'driver': 'native'})
        self.obs = dict(owner_thread_id='root', generation=1,
            observed_at=100, pending_input=False, owner_status={'type': 'idle'},
            quota_observed_at=100, quota={'ordinaryUsageAllowed': True,
                'rateLimits': {'primary': {'usedPercent': 20, 'windowDurationMins': 300}}},
            worker_registry=workers.registry([], 'root'), worker_statuses=[],
            worker_coverage_verified=True, coverage_receipt_id='synthetic-only',
            native_goal_status='active', other_driver_active=False,
            boundary_already_consumed=False)

    def decision(self):
        self.obs['checkpoint_sha256'] = gate.fingerprint(self.cp)
        return gate.decide(self.cp, self.obs, 101)

    def test_native_is_only_driver_even_when_allowed(self):
        result = self.decision()
        self.assertTrue(result['allowed'])
        self.assertFalse(result['external_dispatch_allowed'])

    def test_closed_or_unknown_checkpoint_gates(self):
        for key, value in [('waiting_user', True), ('waiting_user', None),
                ('goal_complete', True), ('continuation_authorized', False),
                ('continuation_authorized', 1)]:
            with self.subTest(key=key, value=value):
                original = copy.deepcopy(self.cp)
                self.cp[key] = value
                self.assertFalse(self.decision()['allowed'])
                self.cp = original
        self.cp['user_stop']['active'] = True
        self.assertFalse(self.decision()['allowed'])
        self.cp['user_stop']['active'] = False
        self.cp['cd5']['enabled'] = False
        self.assertFalse(self.decision()['allowed'])

    def test_activity_coverage_duplicates_and_goal_gates(self):
        for key, value in [('pending_input', True), ('pending_input', None),
                ('observed_at', 80), ('worker_coverage_verified', False),
                ('coverage_receipt_id', ''), ('other_driver_active', True),
                ('boundary_already_consumed', True), ('native_goal_status', 'paused'),
                ('owner_thread_id', 'other'), ('generation', 2),
                ('owner_status', {'type': 'active'}), ('quota_observed_at', 80)]:
            with self.subTest(key=key, value=value):
                original = copy.deepcopy(self.obs)
                self.obs[key] = value
                self.assertFalse(self.decision()['allowed'])
                self.obs = original

    def test_quota_boundary_and_missing_fields(self):
        self.obs['quota']['rateLimits']['primary']['usedPercent'] = 90
        self.assertFalse(self.decision()['allowed'])
        self.obs['quota'] = None
        self.assertFalse(self.decision()['allowed'])
        self.assertFalse(gate.decide({}, {}, 101)['allowed'])

    def test_unknown_worker_read_denies(self):
        self.obs['worker_registry'] = workers.registry([{'session_id': 'root',
            'event': 'SubagentStart', 'agent_id': 'child'}], 'root')
        self.assertFalse(self.decision()['allowed'])

    def test_changed_checkpoint_cannot_reuse_old_observation(self):
        self.obs['checkpoint_sha256'] = gate.fingerprint(self.cp)
        self.cp['next_action']['kind'] = 'different'
        self.assertFalse(gate.decide(self.cp, self.obs, 101)['allowed'])

    def test_current_owner_turn_is_not_an_external_wake(self):
        self.obs.update(execution_context='owner_turn', caller_thread_id='root',
            expected_turn_id='current', host_turn={'id': 'current', 'status': 'inProgress'},
            owner_status={'type': 'active', 'activeFlags': []})
        self.assertTrue(self.decision()['allowed'])
        self.assertFalse(self.decision()['external_dispatch_allowed'])
        for key, value in [('caller_thread_id', 'other'), ('expected_turn_id', 'other'),
                ('host_turn', {'id': 'current', 'status': 'completed'}),
                ('owner_status', {'type': 'active', 'activeFlags': ['waitingOnApproval']})]:
            original = copy.deepcopy(self.obs)
            self.obs[key] = value
            self.assertFalse(self.decision()['allowed'])
            self.obs = original


if __name__ == '__main__':
    unittest.main()
