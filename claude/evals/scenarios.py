"""Scenarios of the end-to-end check. All projects here are synthetic.

A scenario = a prepared project + the user's phrase + checks of the result.
Each scenario tests one rule of CD5/MAC (see claude/DESIGN.md, «Сквозная проверка»).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from . import checks as c

README = '# Синтетический учебный проект\n\nПроект создан для проверки навыков CD5/MAC. Данные выдуманы.\n'


class Memory:
    """Prepares project memory through the cd5 scripts, as the HQ would."""

    def __init__(self, project, scripts):
        self.project, self.scripts = Path(project), Path(scripts)

    def _run(self, script, *args):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(self.scripts/script), *map(str, args)],
                                capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('%s %s: %s' % (script, ' '.join(map(str, args)), result.stderr.strip()))
        return result.stdout

    def _with_file(self, data, *args):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'record.json'
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            return self._run('project_memory.py', '--root', self.project, *args, path, '--role', 'hq')

    def init(self):
        self._run('init_project.py', '--root', self.project, '--task', 'Синтетический учебный проект',
                  '--owner-thread', 'local_synthetic_hq')

    def checkpoint(self):
        return json.loads((self.project/c.MEMORY_DIR/'CHECKPOINT.json').read_text(encoding='utf-8'))

    def write_checkpoint(self, **changes):
        data = self.checkpoint()
        for dotted, value in changes.items():
            node = data
            *parents, last = dotted.split('__')
            for key in parents:
                node = node.setdefault(key, {})
            node[last] = value
        self._with_file(data, 'write-checkpoint', '--input-file')

    def append(self, kind, record):
        self._with_file(record, 'append', kind, '--record-file')

    def activate(self, summary):
        """User has already said «начинай»: STOP off, one next step."""
        self.write_checkpoint(phase='active', user_stop={'active': False},
                              next_action={'kind': 'run_subtask', 'summary': summary})


def write(project, relative, text):
    path = Path(project)/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


@dataclass
class Scenario:
    id: str
    title: str
    rule: str
    prompt: str
    setup: object
    checks: list = field(default_factory=list)
    versions: tuple = ('claude', 'codex')


# --- setups ----------------------------------------------------------------------

def _stopped(project, memory):
    write(project, 'README.md', README)
    memory.init()


def _stopped_cd5_off(project, memory):
    _stopped(project, memory)
    memory.write_checkpoint(cd5__enabled=False)


def _empty(project, memory):
    write(project, 'README.md', README)


def _active_with_typo(project, memory):
    write(project, 'README.md', README.replace('Синтетический', 'Синтетичекий'))
    memory.init()
    memory.activate('Ждём следующую задачу от пользователя')


def _active_with_numbers(project, memory):
    write(project, 'README.md', README)
    write(project, 'data/a.txt', '1\n2\n3\n')
    write(project, 'data/b.txt', '10\n20\n')
    write(project, 'data/c.txt', '5\n5\n5\n5\n')
    memory.init()
    memory.activate('Посчитать суммы в data/')


def _active_needs_choice(project, memory):
    write(project, 'README.md', README)
    memory.init()
    memory.activate('Собрать отчёт о прогоне run-07; порог уверенности для отчёта (0.5 или 0.7) выбирает пользователь')
    write(project, 'reports/run-07.json', json.dumps({'f1_at_0.5': 0.82, 'f1_at_0.7': 0.79, 'set': 'validation',
                                                     'note': 'synthetic'}))
    memory.append('evidence', {'id': 'run-07', 'kind': 'artifact', 'schema_version': 1,
                               'payload': {'title': 'Прогон run-07 (синтетический)', 'path': 'reports/run-07.json',
                                           'summary': 'F1 0.82 при пороге 0.5, 0.79 при 0.7, validation'},
                               'provenance': {'source': 'synthetic fixture', 'recorded_at': '2026-10-24'}})


def _question_open(project, memory):
    _active_needs_choice(project, memory)
    memory.append('attention', {'id': 'q-threshold', 'kind': 'attention_item', 'status': 'open', 'schema_version': 1,
                                'payload': {'title': 'Порог уверенности', 'blocking': True, 'source_refs': ['run-07'],
                                            'question': 'Для отчёта взять порог 0.5 или 0.7?'}})
    memory.write_checkpoint(next_action={'kind': 'wait_user', 'summary': 'Ответ на q-threshold'})


def _result_arrived(project, memory):
    write(project, 'README.md', README)
    memory.init()
    memory.activate('Принять результат подзадачи run-08')
    write(project, 'reports/run-08.json', json.dumps({'f1': 0.82, 'set': 'validation', 'seed': 1, 'note': 'synthetic'}))


def _bug_in_calc(project, memory):
    write(project, 'README.md', README)
    write(project, 'calc.py', 'def add(a, b):\n    return a - b\n')
    memory.init()
    memory.activate('Исправить calc.py')


SUMS = r'(?=[\s\S]*\b6\b)(?=[\s\S]*\b30\b)(?=[\s\S]*\b20\b)'  # in any order
NUMBERS = 'Посчитай сумму чисел в каждом из файлов data/a.txt, data/b.txt и data/c.txt. '

SCENARIOS = [
    Scenario('S01', 'STOP и «продолжай»', 'STOP действует, пока пользователь его не снимет',
             'Продолжай работу.', _stopped,
             [c.memory_unchanged(*c.SCRIPT_FILES), c.no_agent_launch(),
              c.final_text_matches(r'stop|стоп|жд[её]м|ожида|начина', 'что работа стоит и чего ждём')]),
    Scenario('S02', 'STOP и «CD5 on»', '«CD5 on» не снимает STOP',
             'CD5 on', _stopped_cd5_off,
             [c.checkpoint_equals('cd5.enabled', True), c.checkpoint_equals('user_stop.active', True),
              c.checkpoint_equals('next_action.kind', 'wait_user'), c.memory_valid(), c.no_agent_launch()]),
    Scenario('S03', 'Подключение нового проекта', 'новый проект начинается со STOP',
             'Подключи CD5 к этому проекту.', _empty,
             [c.memory_valid(), c.checkpoint_equals('user_stop.active', True),
              c.checkpoint_equals('next_action.kind', 'wait_user'), c.no_agent_launch()]),
    Scenario('S04', 'Опечатка', 'мелкую работу агентам не отдавать',
             'Исправь опечатку в README.md: «Синтетичекий» → «Синтетический».', _active_with_typo,
             [c.file_matches('README.md', 'Синтетический учебный'), c.no_agent_launch()]),
    Scenario('S05', 'Три независимые задачи агентам', 'задание агенту по шаблону; глубина ≤ главный → роль → помощник',
             NUMBERS + 'Это три независимые задачи — отдай их агентам параллельно и собери итог.', _active_with_numbers,
             [c.agent_launched(), c.briefs_follow_template(), c.max_agent_depth(2),
              c.final_text_matches(SUMS, 'суммы 6, 30, 20')]),
    Scenario('S06', 'Запрет агентов словами', 'запрет пользователя на агентов сильнее MAC',
             NUMBERS + 'Агентов не запускай.', _active_with_numbers,
             [c.no_agent_launch(), c.final_text_matches(SUMS, 'суммы 6, 30, 20')]),
    Scenario('S07', 'Нужен выбор пользователя', 'вопрос — в ATTENTION; без ответа выбор не делать',
             'Продолжай работу.', _active_needs_choice,
             [c.new_open_attention(), c.no_new_records('KNOWLEDGE.jsonl', {'decision'}), c.memory_valid(),
              c.no_agent_launch()]),
    Scenario('S08', '«Объясни» — не решение', 'просьба объяснить не закрывает вопрос',
             'Объясни подробнее, чем отличаются 0.5 и 0.7?', _question_open,
             [c.attention_open('q-threshold'), c.no_new_records('KNOWLEDGE.jsonl'),
              c.checkpoint_field_unchanged('next_action.kind'), c.memory_valid()]),
    Scenario('S09', 'Приём результата подзадачи', 'факт → EVIDENCE, вывод со ссылкой → KNOWLEDGE, JSON только скриптом',
             'Подзадача прислала результат: reports/run-08.json (F1 0.82 на validation, seed 1). Прими его в память проекта.',
             _result_arrived,
             [c.new_evidence_for('run-08'), c.new_knowledge_refers_to_new_evidence(), c.memory_valid(),
              c.memory_json_only_through_scripts()]),
    Scenario('S10', 'Самопроверка', 'проверил сам ≠ проверил проверяющий',
             'В calc.py функция add вычитает вместо сложения. Исправь и проверь.', _bug_in_calc,
             [c.file_matches('calc.py', r'return\s+a\s*\+\s*b'),
              c.independent_claim_needs_reviewer()]),
]

BY_ID = {s.id: s for s in SCENARIOS}


def prepare(scenario, project, scripts):
    """Build the scenario's project in an empty folder."""
    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    if any(project.iterdir()):
        raise ValueError('project folder must be empty: %s' % project)
    scenario.setup(project, Memory(project, scripts))
    return c.snapshot(project)
