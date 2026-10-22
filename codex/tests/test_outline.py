"""Readable milestone progress and fresh-project invariants on synthetic plans."""
import json
from pathlib import Path
import tempfile
import unittest
from tools import project_memory as pm
from tools.init_project import initialize


class OutlineTests(unittest.TestCase):
    def test_heading_plan_preserves_statuses_and_criteria(self):
        plan = '''## Риски
### MS-99. Not a milestone
## Вехи проекта
### MS-01. First
**Статус:** завершена.
**Критерий завершения:** evidence checked
**Что получено:** result
### MS-02. Second
**Статус:** в работе. One case is partial.
**Критерии завершения:**
- different independent cases
- sources checked: provenance confirmed
**План:** prepare remaining cases
### MS-03. Third
**Статус:** начата на одном случае; остальное впереди.
### MS-04. Fourth
**Статус:** впереди.
## План текущей вехи MS-02
### MS-88. Not another milestone
'''
        rows=pm._outline_milestones(plan)
        self.assertEqual([r['id'] for r in rows],['MS-01','MS-02','MS-03','MS-04'])
        self.assertEqual([r['status'] for r in rows],['complete','in_progress','in_progress','planned'])
        self.assertEqual(rows[1]['criteria'],['different independent cases','sources checked: provenance confirmed'])
        self.assertEqual(rows[0]['criteria'],['evidence checked'])

    def test_legacy_and_unknown_and_fenced_examples(self):
        rows=pm._outline_milestones('''## Milestones
- [x] `MS-01` — Closed
  - status: complete
  - criteria: checked
- [ ] `MS-02` — Open
  - status: in_progress
### MS-03. Unassessed
**Status:** awaiting decision
```
### MS-90. Example
```
## Other
''')
        self.assertEqual([r['status'] for r in rows],['complete','in_progress','unknown'])
        self.assertEqual(rows[0]['criteria'],['checked'])

    def test_initialize_and_progress_do_not_advance_or_overwrite_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            cp=initialize(root,'Synthetic project','synthetic-owner')
            memory=root/'coordination/cd5'
            before=(memory/'CHECKPOINT.json').read_bytes()
            result=pm.progress_view(root)
            self.assertEqual(result['milestones'][0]['id'],'MS-01')
            self.assertEqual(result['milestones'][0]['status'],'planned')
            self.assertTrue(cp['user_stop']['active'])
            self.assertEqual(cp['owner']['thread_id'],'synthetic-owner')
            self.assertEqual(len(list(memory.iterdir())),5)
            self.assertEqual((memory/'CHECKPOINT.json').read_bytes(),before)
            with self.assertRaises(ValueError): initialize(root,'Other','another-owner')
            self.assertEqual((memory/'CHECKPOINT.json').read_bytes(),before)
