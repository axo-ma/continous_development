import unittest
from tools.project_memory import _outline_milestones


class OutlineMemoryTests(unittest.TestCase):
    def test_readable_headings_and_legacy_list_preserve_explicit_status(self):
        rows = _outline_milestones('''## Вехи проекта
### MS-01. Синтетическая проверка
**Статус:** в работе.
**Критерии завершения:** проверено условие
**Последнее изменение:** проверен пример
### MS-02. Другая проверка
**Статус:** неизвестно
## План текущей вехи MS-01
### MS-99. Это уже не список вех
''')
        self.assertEqual([row['id'] for row in rows], ['MS-01', 'MS-02'])
        self.assertEqual(rows[0]['status'], 'in_progress')
        self.assertEqual(rows[0]['criteria'], ['проверено условие'])
        self.assertEqual(rows[1]['status'], 'unknown')
        old = _outline_milestones('## Milestones\n- [x] `MS-01` — Synthetic\n  - status: complete\n  - criteria: checked\n')
        self.assertEqual(old[0]['status'], 'complete')


if __name__ == '__main__':
    unittest.main()
