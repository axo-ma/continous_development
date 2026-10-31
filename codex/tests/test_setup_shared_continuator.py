"""Shared enrollment/hook preparation; no actual user registry or model calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools.setup_shared_continuator import setup


class SetupSharedTests(unittest.TestCase):
    def test_two_projects_one_hook_group_and_no_permission_change(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)/'service'; roots=[Path(directory)/'hq1',Path(directory)/'hq2']
            hooks=Path(directory)/'hooks.json'
            unrelated={'hooks':[{'type':'command','command':'unrelated-hook'}]}
            hooks.write_text(json.dumps({'hooks':{'Interrupt':[unrelated]}}),encoding='utf-8')
            for i,root in enumerate(roots):
                memory=root/'coordination/cd5';memory.mkdir(parents=True)
                (memory/'CHECKPOINT.json').write_text(json.dumps({'owner':{'thread_id':'owner'+str(i)}}),encoding='utf-8')
                flags=memory/'goal-control';flags.mkdir();(flags/'suspend_HQ').touch()
            with patch('tools.setup_shared_continuator.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"authorized":true}')):
                for root in roots:
                    setup(home,root,hooks,Path(directory)/'cache',Path(directory)/'mac','gpt-6.1-sol')
                setup(home,roots[0],hooks,Path(directory)/'cache',Path(directory)/'mac','gpt-6.1-sol')
            registry=json.loads((home/'REGISTRY.json').read_text(encoding='utf-8'))
            self.assertEqual(len(registry['projects']),2)
            actual=json.loads(hooks.read_text(encoding='utf-8'))['hooks']
            self.assertEqual(actual['Interrupt'][0],unrelated)
            self.assertEqual(len(actual['Interrupt']),2)
            self.assertEqual(len(actual['SessionStart']),1)
            self.assertEqual(len(actual['UserPromptSubmit']),1)
            for root in roots:
                flags=root/'coordination/cd5/goal-control'
                self.assertTrue((flags/'suspend_HQ').exists())
                self.assertFalse((flags/'continue_HQ').exists())
            self.assertFalse((home/'PROCESS.json').exists())
            self.assertFalse((home/'LOGON-BEFORE.json').exists())

    def test_model_denial_leaves_hooks_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);memory=root/'coordination/cd5';memory.mkdir(parents=True)
            (memory/'CHECKPOINT.json').write_text('{"owner":{"thread_id":"owner"}}',encoding='utf-8')
            with patch('tools.setup_shared_continuator.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='')):
                with self.assertRaises(ValueError):
                    setup(root/'service',root,root/'hooks.json',root/'cache',root/'mac','forbidden')
            self.assertFalse((root/'hooks.json').exists())
