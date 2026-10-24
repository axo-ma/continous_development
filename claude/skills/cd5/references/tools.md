# Скрипты

`<skill>` — папка установленного навыка cd5 (обычно `~/.claude/skills/cd5`), `<project>` — корень проекта, `python` — Python 3.10+ (ключ `python` в `.cd5/config.json`, если он записан). Только стандартная библиотека; сеть и модели скрипты не вызывают.

**Всегда запускать с `-X utf8`** (`python -X utf8 <script> …`). На Windows без него русский текст в аргументах портится молча: поиск по русскому слову возвращает пустой список без ошибки, а вывод с кириллицей падает с `UnicodeEncodeError`. В командах ниже `python` = `python -X utf8`.

## Команды

```
python <skill>/scripts/init_project.py --root <project> --task "Название" --owner-thread <sessionId штаба>
python <skill>/scripts/project_memory.py --root <project> validate
python <skill>/scripts/project_memory.py --root <project> pending-attention
python <skill>/scripts/project_memory.py --root <project> query knowledge "слова для поиска" --limit 10
python <skill>/scripts/project_memory.py --root <project> select evidence --id run-07 [--full]
python <skill>/scripts/project_memory.py --root <project> append evidence --record-file <rec.json> --role hq
python <skill>/scripts/project_memory.py --root <project> write-checkpoint --input-file <cp.json> --role hq
python <skill>/scripts/project_memory.py --root <project> archive-attention --id <id> --role hq
python <skill>/scripts/project_memory.py --root <project> progress [--milestone MS-01]
python <skill>/scripts/attention.py --root <project> list | show --id <id> | render --output <file.html>
python <skill>/scripts/cu_archive.py --root <project> budget
```

Запись для `append` и `write-checkpoint` — сначала во временный файл в scratchpad, потом команда. Ошибка скрипта = запись не сделана; прочитать сообщение и исправить запись, а не обходить скрипт.

## Новый проект

`init_project.py` создаёт `.cd5/config.json` и пять файлов. Отказывается, если конфиг уже есть или папка памяти не пуста. Проект начинается со STOP: заполнить OUTLINE (цель, риски, критерии) вместе с пользователем и получить явное «начинай».

Шаблон OUTLINE от скрипта — на английском; переписать на языке пользователя по [outline](outline.md). Вехи держать под заголовком `## Вехи проекта` (или `## Milestones`): веху в другом разделе `progress` не увидит.

## Подключение существующего проекта

Проект уже ведётся (например, со `status.md` по навыку `new-hq`):

1. `init_project.py` — пустая память, STOP активен.
2. OUTLINE — перенести цель, вехи, риски из текущих документов проекта. Не выдумывать статусы и проценты; неизвестное так и помечать.
3. EVIDENCE — каталог существующих отчётов и артефактов (`kind: artifact`), только то, что реально лежит в проекте.
4. KNOWLEDGE — уже принятые решения со ссылками на эти факты. Решение без факта — `kind: decision` без `refs`, с пометкой, откуда оно (например, «docs/decisions.md, 2026-10-12»).
5. ATTENTION — открытые вопросы к пользователю.
6. Показать пользователю, что перенесено, и получить «начинай» — STOP снимается только так.

Старые файлы (`status.md` и т.п.) не удалять без согласия пользователя.

## Форматы записей

Факт (EVIDENCE):

```json
{"id": "run-07", "kind": "artifact", "schema_version": 1,
 "payload": {"title": "Прогон Splitter seed 1", "path": "reports/run-07.json", "summary": "F1 = 0.82 на validation"},
 "provenance": {"source": "подзадача local_…", "recorded_at": "2026-10-24"}}
```

`kind` факта — `artifact`, `source` или `experiment_event` (последний проверяется `experiment_registry.py`, нужен `payload.event_id` = `id`).

Вывод (KNOWLEDGE):

```json
{"id": "k-splitter-seeds", "kind": "conclusion", "schema_version": 1,
 "text": "Результат Splitter устойчив к seed на validation; на train не проверяли.",
 "refs": [{"id": "run-07"}, {"id": "run-08"}]}
```

Принятый результат задачи (KNOWLEDGE, для `progress`):

```json
{"id": "tr-splitter-100", "kind": "task_result", "status": "accepted", "schema_version": 1,
 "task_id": "splitter-100", "milestone_id": "MS-03",
 "goal": "Переобучить Splitter на 100 новых листах", "result": "F1 0.82 ± 0.01 по 3 seed",
 "meaning": "новые листы не ухудшили модель", "refs": [{"id": "run-07"}]}
```

Вопрос пользователю (ATTENTION):

```json
{"id": "q-threshold", "kind": "attention_item", "status": "open", "schema_version": 1,
 "payload": {"title": "Порог уверенности", "question": "Оставить порог 0.5 или поднять до 0.7?",
             "blocking": true, "source_refs": ["k-splitter-seeds"]}}
```

`refs` в KNOWLEDGE должны указывать на существующие id в EVIDENCE — иначе скрипт откажет.

## CHECKPOINT

Не писать с нуля: прочитать текущий, изменить нужные поля, записать через `write-checkpoint`. Обязательные поля (схема 3):

```json
{"schema_version": 3, "phase": "active",
 "owner": {"role": "hq", "thread_id": "local_…"},
 "memory": {"outline": "coordination/cd5/OUTLINE.md", "checkpoint": "coordination/cd5/CHECKPOINT.json",
            "evidence": "coordination/cd5/EVIDENCE.jsonl", "knowledge": "coordination/cd5/KNOWLEDGE.jsonl",
            "attention": "coordination/cd5/ATTENTION.jsonl"},
 "user_stop": {"active": false},
 "next_action": {"kind": "run_subtask", "summary": "Сравнить seed 1–3", "milestone_id": "MS-03"},
 "continuity": {"quota_stop_used_percent": 90},
 "cd5": {"enabled": true}}
```

При активном STOP `next_action.kind` должен быть `wait_user`. Поле `continuity.quota_stop_used_percent` = 90 — для совместимости с Codex, менять нельзя.
