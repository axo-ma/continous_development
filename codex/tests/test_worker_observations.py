"""Synthetic fixtures: no user journals or model calls."""
import unittest
from tools import worker_observations as workers


class WorkerObservationTests(unittest.TestCase):
    def setUp(self):
        self.events = [{'session_id': 'root', 'event': event, 'agent_id': 'child'}
                       for event in ('SubagentStart', 'SubagentStop', 'SubagentStop')]
        self.known = workers.registry(self.events, 'root')
        self.read = dict(owner='root', generation=1, thread_id='child',
                         observed_at=100, status={'type': 'idle'})

    def test_followup_and_rebuild_keep_identity(self):
        self.assertEqual(self.known['workers'], ['child'])
        self.assertEqual(workers.registry(reversed(self.events), 'root'), self.known)
        result = workers.assess(self.known, [self.read], 101, 1)
        self.assertTrue(result['known_workers_idle'])
        self.assertFalse(result['coverage_verified'])

    def test_missing_stale_future_wrong_generation_or_owner_deny(self):
        self.assertFalse(workers.assess(self.known, [], 101, 1)['known_workers_idle'])
        for change in ({'observed_at': 90}, {'observed_at': 102}, {'observed_at': True},
                       {'generation': 2}, {'generation': True}, {'owner': 'other'}):
            self.assertFalse(workers.assess(self.known, [dict(self.read, **change)],
                                           101, 1)['known_workers_idle'])

    def test_busy_waiting_notloaded_and_unknown_deny(self):
        for status in (None, {}, {'type': 'active'}, {'type': 'notLoaded'},
                       {'type': 'systemError'}, {'type': 'idle', 'activeFlags': ['waitingOnApproval']}):
            self.assertFalse(workers.assess(self.known, [dict(self.read, status=status)],
                                           101, 1)['known_workers_idle'])

    def test_interrupt_is_sticky_and_missing_identity_is_unknown(self):
        for extra in ({'session_id': 'root', 'event': 'Interrupt'},
                      {'session_id': 'root', 'event': 'SubagentStart'}):
            known = workers.registry(self.events + [extra], 'root')
            self.assertFalse(workers.assess(known, [self.read], 101, 1)['known_workers_idle'])

    def test_empty_list_never_establishes_complete_coverage(self):
        result = workers.assess(workers.registry([], 'root'), [], 101, 1)
        self.assertFalse(result['coverage_verified'])
        self.assertTrue(result['known_workers_idle'])

    def test_duplicate_status_reads_deny(self):
        self.assertFalse(workers.assess(self.known, [self.read, self.read],
                                       101, 1)['known_workers_idle'])


if __name__ == '__main__':
    unittest.main()
