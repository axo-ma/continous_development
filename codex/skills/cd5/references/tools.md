# Portable command-line tools

For CD5 continuation flags, service admission and HQ completion behavior, follow
[Stop Goal / Continue Goal](file-continuation.md). The native Goal material is
retained as a historical reference only; these tools do not create, resume, or
modify native Goal state for CD5. The agreed project goal and current work remain
in canonical CD5 memory.

`control_units.py begin` accepts optional `--forecast-low`, `--forecast-high`, `--confidence` and `--limit-wu`. `control_units.py budget` revises explicit values with a stable event ID and short reason; see [WU budgets](wu-budgets.md). Forecasts, limits and actuals remain separate; missing values are not zero.

For normal CU usage collection, read [automatic usage](automatic-usage.md). `control_units.py begin/finish` capture the actual caller turn; `cu_auto_telemetry.py` derives factual usage when the report is read. Manual mapping files remain exceptional. No LLM calls or schedules are created by these scripts.

Python 3.10+ and its standard library are required. Use your available Python executable; no particular environment or installation is assumed. In these commands `<skill>` is the installed CD5 folder and `<project>` is the workspace root.

```
python <skill>/scripts/init_project.py --root <project> --task "Task name" --owner-thread <current-thread-id>
python <skill>/scripts/project_memory.py --root <project> validate
python <skill>/scripts/project_memory.py --root <project> query knowledge <terms> --limit 10
python <skill>/scripts/project_memory.py --root <project> progress
python <skill>/scripts/task_ledger.py --root <project> summary --limit 10
python <skill>/scripts/control_units.py --root <project> summary --all
python <skill>/scripts/control_unit_report.py --root <project> --fragment --output <output>/progress.html
python <skill>/scripts/cu_archive.py --root <project> budget
python <skill>/scripts/attention.py --root <project> list
```

Initialization is for a new project only and refuses existing configuration/memory. It starts with explicit STOP: prepare goal, risks and criteria, then obtain authorization to start. The agent provides the actual current thread ID from available metadata; do not ask the user to hunt technical IDs or invent an ID. Existing projects require deliberate adoption through `.cd5/config.json` matching their existing memory_dir and owner_role, without rewriting scientific state. Runtime API role `hq` is a caller assertion; owner_role is the project-specific label in CHECKPOINT, not authentication.

Schema3 CHECKPOINT requires owner/thread_id, exact memory map, explicit user_stop.active and one structured next_action; active STOP requires wait_user. Project config is not a sixth memory log. Leave closed records in cold archives; read only current status and selected evidence at startup. Never load an entire experiment directory just to restore context.

For task lifecycle input and evidence-backed telemetry see `task_ledger.py --help` and `task_telemetry.py --help`. Use explicit logical task IDs and per-participant boundaries; include parent_thread_id for nested helpers. Telemetry rejects wrong ancestry and depth; missing boundaries and counter resets stay unknown. No automatic whole-team usage claim or background interception is provided.

For Control Units and user-facing report commands read [control units](control-units.md). Existing task records remain supported; CU accounting does not require a new task record per tool call. Explicit evidence selection resolves verified cold archives, while ordinary context queries stay bounded to hot memory. `cu_archive.py compact` is a dry-run unless `--apply` is explicitly supplied; installation never compacts live history.

`control_unit_report.py` automatically calculates WU using sibling `work_units.py` and the dated `work_units_rates.json`. Use `--rates <path>` only for an explicit alternate snapshot. Main rows display WU; expanded teams retain exact tokens. Read [work units](work-units.md) before changing rates or interpreting cost as anything beyond a base API estimate. Unknown counters/models are not zero and effort has no separate price multiplier.

experiment_control.py preserves admission checks for protocol hash, approved argv, attempts, STOP and CD5 pause; process exit0 is not semantic success. No imported legacy assessment becomes human gold. project_memory.py writes JSONL through the shared locked API and checkpoints atomically; preserve identity, refs and historical records. Scientific runs still require fresh quota/protocol checks by the caller.

Attention board and local HTML generation work without a custom connector. Interactive follow-up callbacks, side panels, scheduled continuation, quota lookup and chat creation require corresponding host tools. If unavailable, use an explicit question and saved next step; never promise permanent pinning or unattended continuation.
