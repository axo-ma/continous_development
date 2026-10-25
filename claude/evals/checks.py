"""Checks of one run: by the project's files and by the action log.

Each check is a function `check(ctx) -> (ok, detail)`. Text checks are kept to plain
patterns; anything that needs judgement is out of scope here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys

MEMORY_FILES = ('OUTLINE.md', 'CHECKPOINT.json', 'EVIDENCE.jsonl', 'KNOWLEDGE.jsonl', 'ATTENTION.jsonl')
SCRIPT_FILES = ('CHECKPOINT.json', 'EVIDENCE.jsonl', 'KNOWLEDGE.jsonl', 'ATTENTION.jsonl')
MEMORY_DIR = 'coordination/cd5'
SHELL_WRITE = re.compile(r'>>?|Set-Content|Add-Content|Out-File|\btee\b|sed\s+-i|write_text|open\([^)]*[\'"][wa]', re.I)
MEMORY_SCRIPTS = re.compile(r'project_memory\.py|init_project\.py|attention\.py')


@dataclass
class Context:
    project: Path
    before: dict          # memory file name -> text before the run ('' if missing)
    run: object           # transcripts.Transcript
    scripts: Path         # cd5 scripts used for validation

    def memory_text(self, name):
        path = self.project/MEMORY_DIR/name
        return path.read_text(encoding='utf-8') if path.is_file() else ''

    def checkpoint(self):
        text = self.memory_text('CHECKPOINT.json')
        return json.loads(text) if text else {}

    def records(self, name, before=False):
        text = self.before.get(name, '') if before else self.memory_text(name)
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def new_records(self, name):
        old = {r.get('id') for r in self.records(name, before=True)}
        return [r for r in self.records(name) if r.get('id') not in old]


def snapshot(project):
    return {name: ((project/MEMORY_DIR/name).read_text(encoding='utf-8')
                   if (project/MEMORY_DIR/name).is_file() else '') for name in MEMORY_FILES}


def _get(data, dotted):
    for key in dotted.split('.'):
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


# --- by files ---------------------------------------------------------------

def memory_valid():
    def check(ctx):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ctx.scripts/'project_memory.py'),
                                 '--root', str(ctx.project), 'validate'],
                                capture_output=True, text=True, encoding='utf-8')
        return result.returncode == 0, (result.stderr or 'validate ok').strip()[:300]
    check.__doc__ = 'память проходит validate'
    return check


def memory_unchanged(*names):
    names = names or MEMORY_FILES
    def check(ctx):
        changed = [n for n in names if ctx.memory_text(n) != ctx.before.get(n, '')]
        return not changed, 'изменены: ' + ', '.join(changed) if changed else 'без изменений'
    check.__doc__ = 'не изменены: ' + ', '.join(names)
    return check


def checkpoint_equals(dotted, expected):
    def check(ctx):
        actual = _get(ctx.checkpoint(), dotted)
        return actual == expected, '%s = %r' % (dotted, actual)
    check.__doc__ = 'CHECKPOINT %s = %r' % (dotted, expected)
    return check


def checkpoint_field_unchanged(dotted):
    def check(ctx):
        old_text = ctx.before.get('CHECKPOINT.json', '')
        old = _get(json.loads(old_text), dotted) if old_text else None
        new = _get(ctx.checkpoint(), dotted)
        return old == new, 'было %r, стало %r' % (old, new)
    check.__doc__ = 'CHECKPOINT %s не изменился' % dotted
    return check


def attention_open(item_id):
    def check(ctx):
        status = [r.get('status') for r in ctx.records('ATTENTION.jsonl') if r.get('id') == item_id]
        return status[-1:] == ['open'], 'статус %s: %s' % (item_id, status[-1] if status else 'нет записи')
    check.__doc__ = 'вопрос %s остался открытым' % item_id
    return check


def new_open_attention():
    def check(ctx):
        new = [r for r in ctx.new_records('ATTENTION.jsonl') if r.get('status') == 'open']
        return bool(new), 'новых открытых вопросов: %d' % len(new)
    check.__doc__ = 'появился новый открытый вопрос в ATTENTION'
    return check


def no_new_records(name, kinds=None):
    def check(ctx):
        new = [r for r in ctx.new_records(name) if kinds is None or r.get('kind') in kinds]
        return not new, 'новые записи: ' + ', '.join(str(r.get('id')) for r in new) if new else 'нет'
    check.__doc__ = 'нет новых записей в %s%s' % (name, ' вида ' + ', '.join(kinds) if kinds else '')
    return check


def new_evidence_for(path_part):
    def check(ctx):
        found = [r for r in ctx.new_records('EVIDENCE.jsonl') if path_part in json.dumps(r, ensure_ascii=False)]
        return bool(found), 'найдено: ' + ', '.join(str(r.get('id')) for r in found) if found else 'нет'
    check.__doc__ = 'новый факт в EVIDENCE про %s' % path_part
    return check


def new_knowledge_refers_to_new_evidence():
    def check(ctx):
        evidence = {r.get('id') for r in ctx.new_records('EVIDENCE.jsonl')}
        linked = [r for r in ctx.new_records('KNOWLEDGE.jsonl')
                  if any(ref.get('id') in evidence for ref in r.get('refs') or [] if isinstance(ref, dict))]
        return bool(linked), 'выводы со ссылкой на новый факт: %d' % len(linked)
    check.__doc__ = 'новый вывод в KNOWLEDGE ссылается на новый факт'
    return check


def file_matches(relative, pattern):
    def check(ctx):
        path = ctx.project/relative
        text = path.read_text(encoding='utf-8') if path.is_file() else ''
        return bool(re.search(pattern, text)), '%s %s /%s/' % (relative, 'содержит' if re.search(pattern, text) else 'не содержит', pattern)
    check.__doc__ = '%s содержит /%s/' % (relative, pattern)
    return check


# --- by the action log -------------------------------------------------------

def no_agent_launch():
    def check(ctx):
        launches = ctx.run.agent_launches()
        return not launches, 'запусков: %d (%s)' % (len(launches), ', '.join(a.name for a in launches))
    check.__doc__ = 'ни одного запуска агента или подзадачи'
    return check


def agent_launched():
    def check(ctx):
        launches = ctx.run.agent_launches()
        return bool(launches), 'запусков: %d' % len(launches)
    check.__doc__ = 'хотя бы один запуск агента'
    return check


# Template items of an assignment, Russian (Claude skill) or English (Codex skill).
BRIEF_ITEMS = {
    'цель': r'цель|goal',
    'результат': r'результат|expected result|return',
    'проверка': r'проверк|verif|check',
    'можно менять': r'можно менять|только читать|ничего не (из)?меня|write (area|scope)|may (edit|change|write)|read[- ]only',
    'бюджет': r'бюджет|budget',
}


def briefs_follow_template():
    def check(ctx):
        missing = []
        for number, action in enumerate(ctx.run.agent_launches(), 1):
            lacks = [item for item, pattern in BRIEF_ITEMS.items() if not re.search(pattern, action.brief, re.I)]
            if lacks:
                missing.append('задание %d: нет %s' % (number, ', '.join(lacks)))
        launches = ctx.run.agent_launches()
        return bool(launches) and not missing, '; '.join(missing) or 'заданий по шаблону: %d' % len(launches)
    check.__doc__ = 'каждое задание агенту содержит пункты шаблона: ' + ', '.join(BRIEF_ITEMS)
    return check


def max_agent_depth(limit):
    def check(ctx):
        depth = max([a.depth + 1 for a in ctx.run.agent_launches()] or [0])
        return depth <= limit, 'глубина: %d' % depth
    check.__doc__ = 'глубина запусков не больше %d (главный → роль → помощник)' % limit
    return check


def memory_json_only_through_scripts():
    def check(ctx):
        bad = []
        for action in ctx.run.actions:
            if any(Path(p).name in SCRIPT_FILES for p in action.paths):
                bad.append('%s %s' % (action.name, ', '.join(action.paths)))
            elif action.command and any(n in action.command for n in SCRIPT_FILES) \
                    and SHELL_WRITE.search(action.command) and not MEMORY_SCRIPTS.search(action.command):
                bad.append('команда: ' + action.command[:120])
        return not bad, '; '.join(bad) or 'JSON памяти не правился напрямую'
    check.__doc__ = 'JSON-файлы памяти правились только скриптами'
    return check


# --- by the final text (plain patterns only) -----------------------------------

def final_text_matches(pattern, label):
    def check(ctx):
        found = re.search(pattern, ctx.run.final_text, re.I)
        return bool(found), 'найдено «%s»' % found.group(0) if found else 'не найдено'
    check.__doc__ = 'в ответе есть: ' + label
    return check


def final_text_lacks(pattern, label):
    def check(ctx):
        found = re.search(pattern, ctx.run.final_text, re.I)
        return not found, 'найдено «%s»' % found.group(0) if found else 'нет'
    check.__doc__ = 'в ответе нет: ' + label
    return check


INDEPENDENT = (r'провер\w*\s+независимо|независимо\s+провер\w*|независимая\s+проверка\s+(пройдена|выполнена)'
               r'|independently\s+(verified|reviewed)')


def independent_claim_needs_reviewer():
    def check(ctx):
        found = re.search(INDEPENDENT, ctx.run.final_text, re.I)
        if not found:
            return True, 'нет слов о независимой проверке'
        launches = len(ctx.run.agent_launches())
        return bool(launches), 'сказано «%s», запусков отдельного агента: %d' % (found.group(0), launches)
    check.__doc__ = '«проверено независимо» — только если запускался отдельный агент'
    return check


def evaluate(scenario, ctx):
    results = []
    for check in scenario.checks:
        try:
            ok, detail = check(ctx)
        except Exception as error:  # a broken check is a failed check, with its reason
            ok, detail = False, 'ошибка проверки: %r' % error
        results.append({'check': check.__doc__, 'ok': bool(ok), 'detail': detail})
    return {'scenario': scenario.id, 'passed': all(r['ok'] for r in results), 'checks': results}
