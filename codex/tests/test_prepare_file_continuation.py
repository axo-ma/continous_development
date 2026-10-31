"""Preparation is inert, preserves other chats and never writes platform trust."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.prepare_file_continuation import prepare


class PreparationTests(unittest.TestCase):
    def test_idempotent_exact_chat_setup_preserves_stop_and_other_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server, mac, hooks = [root/n for n in ('server.mjs', 'mac.py', 'hooks.json')]
            server.touch()
            mac.touch()
            other = {'hooks': [{'type': 'command', 'command': 'another-command'}]}
            hooks.write_text(json.dumps({'hooks': {'Interrupt': [other]}}), encoding='utf-8')
            args = (root, 'actual-test-chat', server, hooks, mac, 'gpt-6.1-sol')
            first = prepare(*args)
            flags = Path(first['flags'])
            (flags/'stop_planner').touch()
            second = prepare(*args)
            self.assertEqual(first, second)
            self.assertTrue((flags/'stop_planner').exists())
            self.assertFalse((flags/'continue_planner').exists())
            self.assertFalse((flags/'SERVICE.json').exists())
            current = json.loads(hooks.read_text(encoding='utf-8'))
            self.assertEqual(current['hooks']['Interrupt'][0], other)
            self.assertEqual(len(current['hooks']['Interrupt']), 2)
            self.assertEqual(len(current['hooks']['UserPromptSubmit']), 1)
            config = json.loads(Path(first['config']).read_text(encoding='utf-8'))
            self.assertEqual(config['target'], 'actual-test-chat')
            self.assertEqual(config['mode'], 'session')
            self.assertIsNone(config['limit'])
            self.assertFalse(any(root.glob('**/config.toml')))
            with self.assertRaises(ValueError):
                prepare(root, 'another-chat', server, hooks, mac, 'gpt-6.1-sol')
            self.assertEqual(json.loads(hooks.read_text(encoding='utf-8')), current)

    def test_missing_runtime_files_rejected_before_hooks_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = root/'hooks.json'
            with self.assertRaises(ValueError):
                prepare(root, 'test', root/'missing', hooks, root/'missing-mac', 'gpt-6.1-sol')
            self.assertFalse(hooks.exists())
