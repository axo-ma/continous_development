"""Synthetic Goal policy, no real account/chat mutations."""
import copy
import unittest
from tools import native_goal as ng
from tools import planner_control


class NativeGoalTests(unittest.TestCase):
    def setUp(self):
        self.cp = {'owner': {'thread_id': 'synthetic-owner'}, 'cd5': {'enabled': True},
                   'user_stop': {'active': False}, 'next_action': {'kind': 'prepare_protocol'}}
        self.native = {'available': True, 'observed_at': 1000, 'caller_thread_id': 'synthetic-owner', 'goal': None}
        self.quota = {'observed_at': 1000, 'data': {'ordinaryUsageAllowed': True,
                      'rateLimits': {'primary': {'windowDurationMins': 300, 'usedPercent': 20}}}}
        self.activity = {'observed_at': 1000, 'caller_thread_id': 'synthetic-owner',
                         'conflicting_work': False, 'workers_idle': True}
        self.auth = {'create_requested': True}

    def decide(self, **kwargs):
        return ng.plan(self.cp, 'synthetic-owner', 'Prepare the accepted protocol',
                       self.native, self.quota, self.activity, self.auth, now=1000, **kwargs)

    def active(self):
        self.native['goal'] = {'threadId': 'synthetic-owner', 'status': 'active',
            'objective': 'Prepare the accepted protocol', 'tokensUsed': 600, 'tokenBudget': 10000}

    def test_create_then_readback_is_idempotent_and_keeps_accounting(self):
        self.assertEqual(self.decide()['action'], 'create_goal')
        self.assertNotIn('token_budget', self.decide())
        self.active()
        before = copy.deepcopy(self.native)
        for _ in range(2):
            self.assertEqual(self.decide()['action'], 'continue')
        self.assertEqual(self.native, before)
        got = ng.receipt('synthetic-owner', {'goal': self.native['goal']}, now=1000)
        self.assertEqual(got['tokens_used'], 600)
        self.assertFalse(got['quota_reset_resume_verified'])

    def test_start_authorization_and_supported_native_read_required(self):
        self.auth = {}
        self.assertEqual(self.decide()['reason'], 'explicit_goal_authorization_required')
        self.native.pop('goal')
        self.assertEqual(self.decide()['action'], 'get_goal')
        self.native['available'] = False
        self.assertEqual(self.decide()['action'], 'get_goal')

    def test_wrong_owner_and_stale_observations(self):
        self.cp['owner']['thread_id'] = 'other'
        self.assertEqual(self.decide()['action'], 'hold')
        self.cp['owner']['thread_id'] = 'synthetic-owner'
        self.native['goal'] = {'threadId': 'other'}
        self.assertEqual(self.decide()['reason'], 'native_goal_owner_mismatch')
        self.native['observed_at'] = 939
        self.assertEqual(self.decide()['action'], 'get_goal')

    def test_90_percent_ends_without_auto_pause_authorization(self):
        self.active()
        self.quota['data']['rateLimits']['primary']['usedPercent'] = 90
        value = self.decide()
        self.assertEqual(value['action'], 'request_user_pause')
        self.assertTrue(value['end_turn'])
        self.auth['explicit_pause_reasons'] = ['quota90']
        self.assertEqual(self.decide()['action'], 'pause_goal')

    def test_stop_disabled_and_wait_user_have_priority(self):
        self.active()
        self.cp['user_stop']['active'] = True
        self.auth['pause_requested'] = True
        self.assertEqual(self.decide()['reason'], 'user_stop')
        self.cp['user_stop']['active'] = False
        self.cp['cd5']['enabled'] = False
        self.assertEqual(self.decide()['reason'], 'cd5_off')
        self.cp['cd5']['enabled'] = True
        self.cp['next_action']['kind'] = 'wait_user'
        self.assertEqual(self.decide()['reason'], 'wait_user')

    def test_quota_and_activity_unknown_never_admit_creation(self):
        self.quota['observed_at'] = 939
        self.assertEqual(self.decide()['action'], 'hold')
        self.quota['observed_at'] = 1000
        self.quota['data']['rateLimits']['primary']['windowDurationMins'] = 10080
        self.assertEqual(self.decide()['action'], 'hold')
        self.quota['data']['rateLimits']['primary']['windowDurationMins'] = 300
        self.activity['workers_idle'] = None
        self.assertEqual(self.decide()['reason'], 'activity_active_or_unknown')

    def test_existing_goal_conflict_and_terminal_states_never_overwritten(self):
        self.active()
        self.native['goal']['objective'] = 'Different objective'
        self.assertEqual(self.decide()['action'], 'hold')
        self.native['goal']['objective'] = 'Prepare the accepted protocol'
        for status in ['paused', 'blocked', 'usageLimited', 'budgetLimited', 'complete']:
            self.native['goal']['status'] = status
            self.assertEqual(self.decide()['action'], 'wait_user_resume')

    def test_budget_never_inferred_from_wu_or_quota(self):
        self.assertEqual(self.decide(token_budget=100)['action'], 'hold')
        self.auth['token_budget_requested'] = True
        self.assertEqual(self.decide(token_budget=100)['token_budget'], 100)
        with self.assertRaises(ValueError):
            self.decide(token_budget=True)

    def test_completion_requires_audit_not_quota_or_inactivity(self):
        self.active()
        self.cp['goal_status'] = 'verified_complete'
        self.assertEqual(self.decide()['action'], 'verify_completion')
        self.native['goal']['status'] = 'complete'
        self.assertEqual(self.decide()['action'], 'hold')

    def test_external_watchdog_cannot_duplicate_native_goal(self):
        cp = {**self.cp, 'native_goal': {'driver': 'native', 'status': 'active'}}
        state = {'owner_thread_id': 'synthetic-owner', 'state': 'READY',
                 'next_action': 'work', 'authorized': True}
        result = planner_control.decide(state, cp, {}, 1000)
        self.assertEqual(result[0], 'hold')
        self.assertEqual(result[1], 'native_goal_drives_continuation')


if __name__ == '__main__':
    unittest.main()
