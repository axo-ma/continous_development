"""Transient Windows status-file contention must not kill a healthy service."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.planner_control import atomic


class AtomicStatusTests(unittest.TestCase):
    def test_transient_denial_retries_without_losing_previous_state(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'STATUS.json';path.write_text('{"old":true}',encoding='utf-8')
            replace=os.replace
            seen=[]
            def busy_then_replace(source,target):
                seen.append(1)
                if len(seen)==1:
                    self.assertEqual(json.loads(path.read_text()),{'old':True})
                    raise PermissionError('temporary reader')
                replace(source,target)
            with patch('tools.planner_control.os.replace',side_effect=busy_then_replace),patch('tools.planner_control.time.sleep'):
                atomic(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'new':True})

    def test_persistent_failure_preserves_old_state_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'STATUS.json';path.write_text('{"old":true}',encoding='utf-8')
            with patch('tools.planner_control.os.replace',side_effect=PermissionError('denied')),patch('tools.planner_control.time.sleep'):
                with self.assertRaises(PermissionError):atomic(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'old':True})
            self.assertEqual(list(Path(directory).glob('.planner-*')),[])
