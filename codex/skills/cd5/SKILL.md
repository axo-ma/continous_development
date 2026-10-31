---
name: cd5
description: Run sustained tasks with one accountable owner, durable progress records, optional bounded delegation, and safe continuity.
metadata:
  short-description: Long-task workflow
---

# CD5

For an explicitly user-selected two-file continuation service, read
[Stop Goal / Continue Goal](references/file-continuation.md). That choice replaces
native Goal for the selected HQ; do not create/resume a native Goal or run two
drivers there. Installation alone never selects or starts either mechanism.

For ordinary continuous HQ work, first read [Native Goal](references/native-goal.md).
Use the application's actual Goal when explicitly authorized by the user,
including a standing instruction to set a Goal when launching their HQ. OUTLINE
and CHECKPOINT are not native Goal state. The owner reads, creates only if absent,
and verifies its own Goal; preserve existing objectives, usage and lifecycle.
Do not run an external wakeup alongside native continuation. For optional
diagnostics/recovery read [Planner control](references/planner-control.md).
Installation never creates a Goal, starts work or enables a schedule.

For ordinary CU accounting, use [automatic usage](references/automatic-usage.md): capture short begin/finish marks and let code derive factual journal usage at report time. Do not routinely prepare manual telemetry mappings or generate separate accounting narratives.

When planning or delegating a CU, use [WU budgets](references/wu-budgets.md) for a mandatory numeric prospective forecast range for the entire team (use a wider justified range when uncertain), an independently authorized optional limit, executor guidance and comparison with measured actuals. Keep original forecasts and revisions distinct; the Progress Report shows plan and actual, with missing data explained; limits remain in underlying history.

Use CD5 for an explicit long-task workflow or when a task needs durable ownership and continuity. One primary owner remains responsible for scope, integration, decisions, and completion. CD5 can run without MAC; use MAC only when a separate worker materially helps.

Project-local configuration may be stored in `.cd5/config.json`. It may point to a local profile with `profile_file`, set `memory_dir` (default `coordination/cd5`), and set `owner_role`. Resolve paths from the project root. Follow project instructions and any configured profile; do not carry settings from another project.

Read [memory](references/memory.md) for the canonical records and their meaning. For creating or updating the project plan, follow the required [outline contract](references/outline.md): project context → task/scope → expected result → constraints → risks → milestones → current milestone plan. Keep operational state in CHECKPOINT. Read [lifecycle](references/lifecycle.md) before substantive continuation. Read [coordination](references/coordination.md) when delegation is useful, [rotation](references/rotation.md) for owner rotation or handoff, and [attention](references/attention.md) when a human decision is needed.

Use the included [tools](references/tools.md) for initializing new project memory, selective queries, progress and task accounting. Scripts resolve paths from project configuration; no bundled interpreter, external connector or personal project profile is assumed. Discover the installed skill directory rather than guessing a user's home path.

Use **Control Units (CU)** to group work at the user's useful level of control, independently of individual assignments. The **Progress Report** shows those units, results and participant usage, with **Work Units (WU)** as a dated API base-cost estimate and exact tokens inside the team details. For CU recording, bounded active history and the user command **«Покажи прогресс»**, read [control units](references/control-units.md); for tariff interpretation read [work units](references/work-units.md). The report also offers observed five-hour quota-reset windows and saved agent briefs/answers; see control units for their coverage limits. Reuse existing briefs/results; do not produce a separate detailed report or task record for every action. The five canonical current files remain unchanged.

`CD5 on`, `CD5 off`, and `CD5 status` control or report CD5 only; they do not change MAC or clear a user STOP. Preserve the current STOP, protocol, budgets, and permissions when resuming. Do not start a scientific or otherwise budget-consuming run without applicable authorization, an accepted frozen protocol, STOP clearance, and fresh quota below 90% when that gate applies.

At the five-hour quota boundary (usedPercent >= 90), save a minimal checkpoint and end the HQ turn with a final status. Do not remain active by polling or sleeping until reset, launching successors, or starting more work. Follow [lifecycle](references/lifecycle.md) for stop and later readmission.
