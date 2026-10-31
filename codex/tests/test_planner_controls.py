"""Renaming never loses old Stop and never grants permission during migration."""
from pathlib import Path
import tempfile
import unittest
from tools.planner_controls import permission, migrate, user_command, finish_or_wait
from tools.planner_file_hook import handle


class PlannerControlsTests(unittest.TestCase):
    def test_legacy_stop_survives_and_legacy_continue_never_enables(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'Stop Goal').touch()
            (root/'Continue Goal').touch()
            self.assertEqual(permission(root),'stopped')
            migrate(root)
            self.assertTrue((root/'stop_planner').exists())
            self.assertFalse((root/'continue_planner').exists())
            self.assertFalse((root/'Stop Goal').exists())
            self.assertEqual(permission(root),'stopped')
            migrate(root)
            self.assertEqual(permission(root),'stopped')
            user_command(root,'continue')
            self.assertFalse((root/'stop_planner').exists())
            self.assertEqual(permission(root),'continue')

    def test_legacy_continue_alone_and_late_legacy_interrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Continue Goal').touch()
            self.assertEqual(permission(root),'idle')
            migrate(root)
            self.assertEqual(permission(root),'idle')
            user_command(root,'continue')
            (root/'Stop Goal').touch()  # Prior trusted snapshot during transition.
            self.assertEqual(permission(root),'stopped')
            event=dict(session_id='target',hook_event_name='UserPromptSubmit')
            handle(dict(event,prompt='Continue Goal'),'target',root)
            self.assertEqual(permission(root),'stopped')
            handle(dict(event,prompt='Continue Planner'),'target',root)
            self.assertEqual(permission(root),'continue')
            finish_or_wait(root)
            self.assertEqual(permission(root),'idle')

    def test_new_commands_and_interrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);event=dict(session_id='target',hook_event_name='UserPromptSubmit')
            handle(dict(event,prompt='Stop Planner'),'target',root)
            self.assertEqual(permission(root),'stopped')
            handle(dict(event,prompt=' Continue Planner '),'target',root)
            self.assertEqual(permission(root),'continue')
            handle(dict(event,hook_event_name='Interrupt'),'target',root)
            self.assertTrue((root/'stop_planner').exists())
