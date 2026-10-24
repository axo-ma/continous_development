import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.report_memory import project_snapshots


class MemoryReportTests(unittest.TestCase):
    def test_current_files_custom_layout_partial_data_and_no_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.cd5').mkdir()
            (root / '.cd5/config.json').write_text(json.dumps({'memory_dir': 'memory'}))
            memory = root / 'memory'
            memory.mkdir()
            fixtures = {
                'OUTLINE.md': '# Synthetic plan',
                'CHECKPOINT.json': json.dumps({'owner': {'role': 'hq'}, 'user_stop': {'active': False}}),
                'KNOWLEDGE.jsonl': json.dumps({'id': 'K1', 'kind': 'observation', 'payload': {
                    'conclusion': 'Saved finding', 'limitations': 'Untested elsewhere', 'refs': [{'id': 'E1'}]}}) + '\n{bad\n',
                'ATTENTION.jsonl': '\n'.join(json.dumps(row) for row in [
                    {'id': 'A1', 'kind': 'attention_item', 'status': 'open', 'event': {'question': 'Choose a route?'}},
                    {'id': 'A2', 'kind': 'attention_item', 'status': 'closed', 'payload': {'question': 'Old question'}},
                    {'id': 'A3', 'kind': 'attention_archive_ref', 'status': 'closed', 'archive_path': '../outside.json'}])}
            for name, text in fixtures.items():
                (memory / name).write_text(text, encoding='utf-8')
            before = {path.name: path.read_bytes() for path in memory.iterdir()}
            data = project_snapshots(root)
            self.assertEqual(data['outline']['markdown'], '# Synthetic plan')
            self.assertEqual(data['checkpoint']['state']['user_stop'], False)
            self.assertEqual(data['knowledge']['status'], 'partial')
            entry = data['knowledge']['entries'][0]
            self.assertEqual(entry['text'], 'Saved finding')
            self.assertEqual(entry['limitations'], 'Untested elsewhere')
            self.assertEqual(entry['sources'], [{'id': 'E1'}])
            self.assertEqual([row['id'] for row in data['attention']['open']], ['A1'])
            self.assertEqual(len(data['attention']['history']), 2)
            self.assertIn('Архив недоступен', data['attention']['history'][0]['description'])
            self.assertEqual(before, {path.name: path.read_bytes() for path in memory.iterdir()})

    def test_malformed_archive_keeps_report_and_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = root / 'coordination/cd5'
            memory.mkdir(parents=True)
            (memory / 'ATTENTION.jsonl').write_text(json.dumps({'id': 'A1', 'kind': 'attention_archive_ref', 'status': 'closed'}))
            with patch('tools.project_memory._archived_attention', side_effect=AttributeError('bad archive shape')):
                data = project_snapshots(root)
            self.assertEqual(data['attention']['status'], 'partial')
            self.assertEqual(data['attention']['open'], [])
            self.assertIn('Архив недоступен', data['attention']['history'][0]['description'])

    def test_missing_is_not_empty_and_invalid_checkpoint_is_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = project_snapshots(root)
            self.assertEqual(data['knowledge']['status'], 'missing')
            self.assertEqual(data['knowledge']['entries'], [])
            memory = root / 'coordination/cd5'
            memory.mkdir(parents=True)
            (memory / 'CHECKPOINT.json').write_text('[]')
            data = project_snapshots(root)
            self.assertEqual(data['checkpoint']['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
