"""Two control files and sequential sends; no real Desktop/model calls."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools.file_continuation_service import FileService
from tools.planner_controls import permission, user_command, finish_or_wait
from tools.planner_file_hook import handle


class FileContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = dict(flags=str(self.root), status=str(self.root/'STATUS.json'),
            target='test', limit=3, mac_script='synthetic', model='gpt-6.1-sol', message='continue')
        self.calls = []
        self.turn = dict(id='initial', status='completed')
        self.host = {'type': 'idle'}
        self.used = 20
        self.sends = 0
        self.fail = False
        self.service = FileService(self.config, self)
        mock = patch('tools.file_continuation_service.subprocess.run',
            return_value=SimpleNamespace(returncode=0, stdout='{"authorized":true}'))
        mock.start()
        self.addCleanup(mock.stop)

    def call(self, name, args):
        self.calls.append(name)
        if name == 'read_thread':
            return dict(thread=dict(id='test', status=self.host), turns=[self.turn])
        if name == 'get_usage_limits':
            return dict(ordinaryUsageAllowed=True, rateLimits=dict(primary=dict(
                usedPercent=self.used, windowDurationMins=300)))
        self.assertEqual(name, 'send_message_to_thread')
        self.sends += 1
        if self.fail:
            raise TimeoutError()
        return dict(threadId='test')

    def test_absent_and_stop_never_read_or_send(self):
        self.assertEqual(self.service.tick()['reason'], 'idle')
        user_command(self.root, 'continue')
        user_command(self.root, 'stop')
        self.assertEqual(permission(self.root), 'stopped')
        self.assertEqual(self.service.tick()['reason'], 'stopped')
        self.assertEqual(self.calls, [])

    def test_sequential_wait_and_independent_limit(self):
        user_command(self.root, 'continue')
        for n in range(3):
            self.assertEqual(self.service.tick()['reason'], 'sent')
            self.assertEqual(self.service.tick()['reason'], 'awaiting_sent_turn_no_duplicate')
            self.turn = dict(id=str(n), status='inProgress')
            self.assertEqual(self.service.tick()['reason'], 'waiting_for_result')
            self.turn['status'] = 'completed'
        self.assertEqual(self.service.tick()['reason'], 'trial_limit_reached')
        self.assertEqual(self.sends, 3)

    def test_quota_gate_preserves_permission_and_automatically_reopens(self):
        user_command(self.root, 'continue')
        before=(self.root/'continue_planner').stat().st_mtime_ns
        self.used = 90
        self.assertEqual(self.service.tick()['reason'], 'quota_closed')
        self.used = 100
        self.assertEqual(self.service.tick()['reason'], 'quota_closed')
        self.assertEqual(self.sends, 0)
        self.assertEqual((self.root/'continue_planner').stat().st_mtime_ns,before)
        self.used = 0
        self.assertEqual(self.service.tick()['reason'], 'sent')
        self.assertEqual(self.sends, 1)

    def test_manual_stop_during_quota_pause_survives_reset_and_restart(self):
        user_command(self.root, 'continue')
        self.used=90
        self.service.tick()
        user_command(self.root,'stop')
        self.used=0
        other=FileService(self.config,self,dict(self.service.status))
        self.assertEqual(other.tick()['reason'],'stopped')
        self.assertEqual(self.sends, 0)

    def test_old_sticky_quota_state_does_not_require_new_continue(self):
        user_command(self.root,'continue')
        saved=dict(self.service.status,quota_hold_permission=(self.root/'continue_planner').stat().st_mtime_ns)
        other=FileService(self.config,self,saved)
        self.assertEqual(other.tick()['reason'],'sent')
        self.assertNotIn('quota_hold_permission',other.status)

    def test_session_continues_beyond_trial_limit_until_stop(self):
        config = dict(self.config, mode='session', session_authorized=True, limit=None)
        service = FileService(config, self)
        user_command(self.root, 'continue')
        for n in range(5):
            self.assertEqual(service.tick()['reason'], 'sent')
            self.turn = dict(id=str(n), status='completed')
        user_command(self.root, 'stop')
        self.assertEqual(service.tick()['reason'], 'stopped')
        self.assertEqual(self.sends, 5)
        # Explicit Continue removes Stop, without resetting the send history.
        user_command(self.root, 'continue')
        self.assertEqual(service.tick()['reason'], 'sent')
        self.assertEqual(service.status['used'], 6)

    def test_session_requires_explicit_authorization(self):
        for config in [dict(self.config, mode='session', limit=None),
                       dict(self.config, limit=None), dict(self.config, limit=True)]:
            with self.assertRaises(ValueError):
                FileService(config, self)

    def test_bad_saved_state_and_other_chat_are_rejected(self):
        for changes in [dict(waiting='false'), dict(uncertain=None), dict(target='other')]:
            with self.assertRaises(ValueError):
                FileService(self.config, self, dict(self.service.status, **changes))

    def test_stop_arriving_during_quota_read_prevents_send(self):
        user_command(self.root, 'continue')
        original = self.call
        def stopping(name, args):
            result = original(name, args)
            if name == 'get_usage_limits':
                user_command(self.root, 'stop')
            return result
        with patch.object(self, 'call', side_effect=stopping):
            self.assertEqual(self.service.tick()['reason'], 'permission_removed_before_send')
        self.assertEqual(self.sends, 0)

    def test_uncertain_send_not_retried_after_reload(self):
        user_command(self.root, 'continue')
        self.fail = True
        with self.assertRaises(TimeoutError):
            self.service.tick()
        other = FileService(self.config, self, dict(self.service.status))
        self.assertEqual(other.tick()['reason'], 'send_outcome_unknown_no_retry')
        self.assertEqual(self.sends, 1)

    def test_interrupt_and_literal_user_commands_only(self):
        event = dict(session_id='test', hook_event_name='Interrupt')
        handle(event, 'test', self.root)
        self.assertEqual(permission(self.root), 'stopped')
        handle(dict(event, session_id='other'), 'other-target', self.root)
        handle(dict(event, hook_event_name='UserPromptSubmit', prompt='Automatic Continue Planner please'), 'test', self.root)
        self.assertEqual(permission(self.root), 'stopped')
        result = handle(dict(event, hook_event_name='UserPromptSubmit', prompt='Continue Planner'), 'test', self.root)
        self.assertEqual(result['decision'], 'block')
        self.assertEqual(permission(self.root), 'continue')
        finish_or_wait(self.root)
        self.assertEqual(permission(self.root), 'idle')


if __name__ == '__main__':
    unittest.main()
