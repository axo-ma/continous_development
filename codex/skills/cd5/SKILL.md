---
name: cd5
description: Run sustained tasks with one accountable owner, durable progress records, optional bounded delegation, and safe continuity.
metadata:
  short-description: Long-task workflow
---

# CD5

Architecture: **CD5 Continuator and Controls**. Read the concise
[architecture contract](references/continuous-planner-contract.md) first.
Controls are `continue_HQ` (user-owned Continuator enable choice) and
`suspend_HQ` (HQ suspension). Only explicit user enable/disable changes
continue_HQ. HQ start/continue removes suspend_HQ; HQ stop/Interrupt creates it.
HQ creates suspend_HQ only at whole-plan completion or an evidenced mandatory human/system dependency blocking all remaining work, never removes
continue_HQ by its own decision. Quota>=90 changes neither file: finish the turn;
one shared hidden service waits without a model and resumes below90 when admitted.
The service sends only «Продолжай». Read [continuation](references/file-continuation.md).
One service per Windows user handles explicitly enrolled HQs sequentially, using
CHECKPOINT.owner.thread_id. Each HQ keeps its five memory files. Native agent
Goal is not the CD5 driver; do not create, resume, update or clear it for CD5.
Installation alone never enrolls, enables or starts an HQ.

The former native Goal instructions in [native-goal.md](references/native-goal.md)
are retained as historical evidence only. Installation never creates a Goal,
starts work, enrolls an HQ, or enables a schedule.

For ordinary CU accounting, use [automatic usage](references/automatic-usage.md): bind each actual owner turn once to its CU, retain worker assignment boundaries, and let code derive factual journal usage at report time. Do not routinely prepare manual telemetry mappings or generate separate accounting narratives.

When planning or delegating a CU, use [WU budgets](references/wu-budgets.md) for a mandatory numeric prospective forecast range for the entire team (use a wider justified range when uncertain), an independently authorized optional limit, executor guidance and comparison with measured actuals. Keep original forecasts and revisions distinct; the Progress Report shows plan and actual, with missing data explained; limits remain in underlying history.

Read [HQ authority](references/hq-authority.md) for delegated plan decisions: HQ itself approves/version-controls protocols, internal budgets and repairs; do not turn these into requests for renewed human permission.

Use CD5 for an explicit long-task workflow or when a task needs durable ownership and continuity. One primary owner remains responsible for scope, integration, decisions, and completion. CD5 can run without MAC; use MAC only when a separate worker materially helps.

Project-local configuration may be stored in `.cd5/config.json`. It may point to a local profile with `profile_file`, set `memory_dir` (default `coordination/cd5`), and set `owner_role`. Resolve paths from the project root. Follow project instructions and any configured profile; do not carry settings from another project.

Read [memory](references/memory.md) for the canonical records and their meaning. For creating or updating the project plan, follow the required [outline contract](references/outline.md): project context → task/scope → expected result → constraints → risks → milestones → current milestone plan. Keep operational state in CHECKPOINT. Read [lifecycle](references/lifecycle.md) before substantive continuation. Read [coordination](references/coordination.md) when delegation is useful, [rotation](references/rotation.md) for owner rotation or handoff, and [attention](references/attention.md) when a human decision is needed.

Use the included [tools](references/tools.md) for initializing new project memory, selective queries, progress and task accounting. Scripts resolve paths from project configuration; no bundled interpreter, external connector or personal project profile is assumed. Discover the installed skill directory rather than guessing a user's home path.

Use **Control Units (CU)** to group work at the user's useful level of control, independently of individual assignments. The **Progress Report** shows those units, results and participant usage, with **Work Units (WU)** as a dated API base-cost estimate and exact tokens inside the team details. For CU recording, bounded active history and the user command **«Покажи прогресс»**, read [control units](references/control-units.md); for tariff interpretation read [work units](references/work-units.md). The report also offers observed five-hour quota-reset windows and saved agent briefs/answers; see control units for their coverage limits. Reuse existing briefs/results; do not produce a separate detailed report or task record for every action. The five canonical current files remain unchanged.

`CD5 on`, `CD5 off`, and `CD5 status` control or report CD5 only; they do not change MAC or clear a user STOP. Preserve direct user STOP, actual user limits, historical protocol versions and mandatory system permissions. The assigned plan authorizes HQ to select and internally approve/version its steps, protocols and budgets; no repeated human signoff is implied. Before a run HQ checks scope, its recorded protocol version, duplication and fresh quota below90. Internal forecast/allocation exhaustion routes to HQ revision, never automatically to the user.

At the five-hour quota boundary (usedPercent >= 90), save a minimal checkpoint and end the HQ turn with a final status. Do not remain active by polling or sleeping until reset, launching successors, or starting more work. Follow [lifecycle](references/lifecycle.md) for stop and later readmission.
