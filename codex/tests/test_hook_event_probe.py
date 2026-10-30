"""Synthetic fixtures only; no actual hooks, chats or user history."""
import json
from pathlib import Path
import tempfile
import unittest
from tools import hook_event_probe as probe


class HookEventProbeTests(unittest.TestCase):
    def test_unrelated_sessions_and_unknown_events_do_nothing(self):
        for event in (None, {}, {'session_id': 'other', 'hook_event_name': 'Stop'},
                      {'session_id': 'test', 'hook_event_name': 'Unknown'}):
            self.assertIsNone(probe.observation(event, 'test'))

    def test_records_identity_without_claiming_completion(self):
        row = probe.observation({'session_id': 'test', 'hook_event_name': 'SubagentStop',
            'agent_id': 'child', 'turn_id': 'turn', 'last_assistant_message': 'private',
            'transcript_path': 'private', 'tool_input': 'private'}, 'test')
        self.assertEqual(row['agent_id'], 'child')
        self.assertFalse(row['terminal_completion_proven'])
        self.assertNotIn('private', json.dumps(row))

    def test_duplicate_events_are_separate_observations_not_extra_launches(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name) / 'events'
            event = {'session_id': 'test', 'hook_event_name': 'Interrupt'}
            for _ in range(2):
                self.assertTrue(probe.record(event, 'test', directory))
            self.assertEqual(len(list(directory.glob('*.json'))), 2)
            for path in directory.glob('*.json'):
                row = json.loads(path.read_text(encoding='utf-8'))
                self.assertTrue(row['manual_interrupt_observed'])
                self.assertNotIn('decision', row)


if __name__ == '__main__':
    unittest.main()
