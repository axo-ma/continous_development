"""ATTENTION is append-only: closing a question appends a row and never rewrites the question."""
from pathlib import Path
import shutil
import tempfile
import unittest

from tools import project_memory as pm
from tools.init_project import initialize

BUNDLE = Path(__file__).resolve().parents[1]


def question(item_id, text):
    return {'id': item_id, 'kind': 'attention_item', 'status': 'open', 'schema_version': 1,
            'payload': {'title': item_id, 'question': text, 'blocking': True}}


class AttentionAppendOnlyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='.attention-test-', dir=BUNDLE))
        self.addCleanup(lambda: shutil.rmtree(self.root))
        initialize(self.root, 'Synthetic', 'chat-A')
        self.file = self.root/'coordination/cd5/ATTENTION.jsonl'
        pm.append(self.root, 'attention', question('q-threshold', 'Порог 0.5 или 0.7?'), 'hq')
        pm.append(self.root, 'attention', question('q-seeds', 'Гонять ещё seed?'), 'hq')

    def test_close_appends_and_keeps_the_question_line(self):
        before = self.file.read_text(encoding='utf-8')
        row = pm.close_attention(self.root, 'q-threshold', 'hq', 'порог 0.5')
        after = self.file.read_text(encoding='utf-8')
        self.assertTrue(after.startswith(before))
        self.assertEqual((row['kind'], row['ref'], row['decision']), ('attention_close', 'q-threshold', 'порог 0.5'))
        self.assertEqual([i['id'] for i in pm.pending_attention(self.root)], ['q-seeds'])
        pm.validate(self.root)

    def test_closed_question_is_hidden_unless_asked_and_carries_the_decision(self):
        pm.close_attention(self.root, 'q-threshold', 'hq', 'порог 0.5')
        self.assertEqual(pm.select(self.root, 'attention', ['q-threshold']), [])
        closed = pm.select(self.root, 'attention', ['q-threshold'], full=True, include_closed=True)[0]
        self.assertEqual((closed['status'], closed['decision']), ('closed', 'порог 0.5'))
        self.assertEqual([r['id'] for r in pm.query(self.root, 'attention', 'seed порог')], ['q-seeds'])

    def test_cannot_close_twice_or_update_closed_or_close_unknown(self):
        pm.archive_attention(self.root, 'q-threshold', 'hq')  # former name still closes
        with self.assertRaisesRegex(pm.MemoryError, 'already closed'):
            pm.close_attention(self.root, 'q-threshold', 'hq')
        with self.assertRaisesRegex(pm.MemoryError, 'closed attention item cannot be updated'):
            pm.record_attention_click(self.root, 'q-threshold')
        with self.assertRaisesRegex(pm.MemoryError, 'not found'):
            pm.close_attention(self.root, 'q-missing', 'hq')

    def test_close_rows_cannot_be_appended_by_hand(self):
        with self.assertRaisesRegex(pm.MemoryError, 'attention kind'):
            pm.append(self.root, 'attention', {'id': 'q-seeds.closed', 'kind': 'attention_close',
                                               'ref': 'q-seeds', 'schema_version': 1}, 'hq')


if __name__ == '__main__':
    unittest.main()
