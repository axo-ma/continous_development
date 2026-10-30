"""Synthetic fixtures only; no Desktop connection or real account reads."""
import json
from pathlib import Path
import tempfile
import os
import subprocess
import sys
import unittest
from tools import stop_hook_trial as trial


class StopTrialTests(unittest.TestCase):
    def test_main_output_with_windows_legacy_encoding(self):
        code = ('import sys;sys.path.insert(0,sys.argv[1]);import stop_hook_trial as t;'
                't.run=lambda *a:{"decision":"block","reason":"\\u0428\\u0430\\u0433"};'
                'sys.argv=["trial","--state","unused"];t.main()')
        result = subprocess.run([sys.executable, '-c', code, str(Path(trial.__file__).parent)],
            input='{}', capture_output=True, text=True, encoding='ascii',
            env=dict(os.environ, PYTHONIOENCODING='cp1252'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['reason'], '\u0428\u0430\u0433')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.json'
        self.state = dict(target='synthetic', owner='synthetic', generation=1,
            authorized=True, stop=False, waiting_user=False, goal_complete=False,
            workers_idle=True, goal_absent=True, driver='stop_trial',
            remaining_step='CD5_STOP_STEP_TWO')
        self.event = dict(session_id='synthetic', hook_event_name='Stop',
            turn_id='turn-one', stop_hook_active=False,
            last_assistant_message='CD5_STOP_STEP_ONE')
        self.quota = dict(ordinaryUsageAllowed=True, rateLimits=dict(
            primary=dict(windowDurationMins=300, usedPercent=84)))
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.state), encoding='utf-8')

    def test_one_continuation_and_duplicate_denied(self):
        calls = []
        def read(env, state):
            calls.append(1)
            return self.quota
        self.assertEqual(trial.run(self.event, self.path, {}, read)['decision'], 'block')
        self.assertEqual(trial.run(self.event, self.path, {}, read), {})
        self.assertEqual(calls, [1])

    def test_all_closed_gates_make_no_connection(self):
        changes = [dict(stop=True), dict(authorized=False), dict(waiting_user=True),
            dict(goal_complete=True), dict(workers_idle=False), dict(workers_idle=None),
            dict(owner='other'), dict(generation=2), dict(goal_absent=False),
            dict(driver='native')]
        for change in changes:
            with self.subTest(change=change):
                state = dict(self.state, **change)
                self.assertFalse(trial.admitted(self.event, state))
        for change in [dict(session_id='other'), dict(stop_hook_active=True),
                       dict(stop_hook_active=None), dict(turn_id=''),
                       dict(last_assistant_message='done')]:
            self.assertFalse(trial.admitted(dict(self.event, **change), self.state))

    def test_quota_boundary_unknown_and_denied(self):
        for percent in [90, 100, None, -1, True, float('nan')]:
            self.quota['rateLimits']['primary']['usedPercent'] = percent
            self.assertFalse(trial.quota_allowed(self.quota))
        self.assertFalse(trial.quota_allowed({}))
        self.assertFalse(trial.quota_allowed(dict(self.quota, ordinaryUsageAllowed=False)))

    def test_connection_failure_never_retried(self):
        def fail(env, state):
            raise RuntimeError()
        self.assertEqual(trial.run(self.event, self.path, {}, fail), {})
        self.assertEqual(trial.run(self.event, self.path, {}, lambda *a: self.quota), {})

    def test_interrupt_and_owner_change_during_read(self):
        def interrupt(env, state):
            trial.run(dict(self.event, hook_event_name='Interrupt'), self.path, {})
            return self.quota
        self.assertEqual(trial.run(self.event, self.path, {}, interrupt), {})
        self.assertTrue(json.loads(self.path.read_text())['stop'])

    def test_reserved_receipt_not_replayed_after_restart(self):
        self.path.with_name('receipt.json').write_text('{"decision":"reserved_unconfirmed"}')
        self.assertEqual(trial.run(self.event, self.path, {}, lambda *a: self.quota), {})


if __name__ == '__main__':
    unittest.main()
