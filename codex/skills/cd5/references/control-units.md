# Control Units and Progress Report

A Control Unit (CU) is the user-facing reporting group for work toward one expected result. It is a concept, not a sixth canonical file or a required file per assignment. A CU may span turns, chats, protocols and several agents. Existing scientific authorization, quotas and budgets remain separate and controlling.

The owner chooses the useful granularity. If the user finds CUs too fine or broad, adjust future grouping; do not rewrite past claims or imply retrospective boundaries were recorded prospectively. Prompts, tool calls and routine corrections do not automatically create CUs. A delegation can implement a whole CU or only part of one. Keep all related assignments under the same `cu_id`; MAC supplies participant ancestry, but single-owner work works without MAC.

## Minimal operating contract

At a new substantive result, record `open` once with stable `cu_id`, short title and goal. The current owner is automatically included as HQ; optional actual `model`/`reasoning` facts can be supplied at open. Reuse the existing assignment as description/source; do not generate a second narrative for reporting. If work continues toward the same result, keep the CU, including across owner rotation. Register each additional assigned participant once. Link an existing `task_id` only when one already exists; no new task ledger entry is required for every action.

When a result exists, record `status=completed` with its short outcome and existing result sources. Negative/limited results can complete a CU without making a milestone complete. A `paused` CU has no completion date and is not a completed result; `cancelled` means work was deliberately abandoned. Resumption returns paused to open. Project-wide STOP is the existing CHECKPOINT state, separate from individual CU states. Recording/reporting does not clear STOP or authorize work. A completed/cancelled CU is not silently reopened; use a new linked piece of work when appropriate.

Only the actual current CHECKPOINT owner may change CU metadata. Pass its actual `caller_thread_id`; do not impersonate an owner to bootstrap another chat. These checks are cooperative workflow checks, not cryptographic authentication. Reviewers/helpers return results to their caller and do not run a new reporting bureaucracy.

Use `scripts/control_units.py --root <project> record --record-file <json> --caller-thread <actual-id>`. Input examples:

```json
{"event_id":"cu-comparison-open","action":"open","cu_id":"CU-compare","title":"Compare FULL and COMPACT","goal":"Determine whether compression preserves useful answers","description":"Reuse the existing brief here, or supply its source reference."}
```

```json
{"event_id":"cu-comparison-participant","action":"participant","cu_id":"CU-compare","participant":{"thread_id":"actual-thread-id","name":"Executor","role":"executor","parent_thread_id":"actual-parent-thread-id","model":"actual-model","reasoning":"actual-effort"}}
```

```json
{"event_id":"cu-comparison-done","action":"status","cu_id":"CU-compare","status":"completed","result":"Compression failed on the selected case; broader usefulness remains unknown.","sources":[{"label":"Existing result","path":"results/comparison/REPORT.md"}]}
```

Stable event IDs make retries idempotent; changing an event requires a new ID. Optional `at` must include a timezone; supplied historical boundaries require `historical=true` on open and must not be passed off as prospective. Sources may also carry already saved `text`, `thread_id` and `turn_id`. They are references, not permission to read arbitrary external files. Text fields are bounded. The program never reads a source path automatically or calls an LLM to produce a report.

## Accounting

CU planning may also carry a [WU forecast and separate limit](wu-budgets.md). Both are whole-team values, optional and revisioned; neither replaces factual usage. The user-facing report shows plan (forecast) and actual WU; it does not display limits or limit comparisons, including in CU details. Preserve existing limit records and the original forecast in the underlying event history.

The normal path is [automatic usage](automatic-usage.md). CU open/status records capture an owner-turn anchor; the progress reader derives usage from verified journals without extra measurement events or manual mapping files. The explicit mapping API below remains for exceptional/historical sources and established manual measurements.

Use the existing verified rollout interval mapping via `control_units.py collect --cu <id> --mapping <json> --event-id <stable-id> --caller-thread <actual-id>`. Register measured participants first and map the task to the CU (mapping `task_id` may equal `cu_id`; otherwise record `action=link_task`). Parent IDs, roles and interval boundaries must match their sources. Merely having launch metadata does not supply usage measurements.

One source interval cannot be attributed twice or to multiple CUs. Identical reimports are deduplicated. Parent/child totals stay unknown unless their counters are independently scoped and that observation has an existing EVIDENCE witness supplied with `--exclusive-scope-evidence <id>`. Supplying a witness ID is an explicit caller assertion that its content establishes independent counter scopes; do not fabricate a witness merely to make totals appear. Missing participants, baselines or reset counters remain unknown. Reasoning is already inside output. Local inference remains separate.

The Progress Report displays **Work Units (WU)** in its main cost column and keeps the exact three token columns inside the expanded team. Read [work units](work-units.md) when interpreting or changing the dated base-cost estimator. It is not subscription usage or a scheduling budget; model/coverage unknowns must remain visible.

Elapsed CU lifetime, measured elapsed turns and active computing time are different. The report labels them; night pauses must not be called work. Do not sum parallel agents' elapsed times into task duration. A token snapshot count is not a request count. This version collects explicit mappings; it does not intercept arbitrary model calls or automatically guess task boundaries.

## Project memory access

A visible plan control opens a readable snapshot of the configured OUTLINE.md. KNOWLEDGE and ATTENTION controls must also be present even when CU history is empty. KNOWLEDGE opens saved findings with search and pages, preserving record types, limitations and source references. ATTENTION separates open questions from closed history. The report loads these current memory snapshots automatically with `--root`, independently of CU date filters. Missing, malformed and partial sources have visible diagnostics; they must not appear as empty registers. Viewing does not accept findings, resolve questions, send messages or authorize work. These are generated snapshots, refreshed by invoking the report again.

The report displays plan and actual WU only, including CU details. Existing limit history remains in canonical data but is not displayed. Missing forecasts have an explicit explanation. Individually measured participants may be shown when the team total is unknown; never sum participants without proven independent scopes.

## User invocation

The agreed command is **«Покажи прогресс»**, in a project chat. Generate a fresh read-only snapshot with the complete available CU history, including cold history, and show its latest 10 CUs on the first page. **«Раньше →»** and **«← Новее»** browse consecutive pages of 10 without another chat command or a model call. Show the visible range and total count; disable navigation at the corresponding boundary. Do not replace this history with hard-coded demo slices or participant-count tabs. A repeat command rebuilds the snapshot. The command does not start research, mutate CU states or create schedules. The JSON summary API can still default to latest 10; the interactive renderer explicitly loads the whole selection.

- «Покажи прогресс за неделю» / a date range: resolve dates using the user's timezone, then pass `--since YYYY-MM-DD --until YYYY-MM-DD` (inclusive calendar dates).
- «Покажи прогресс за всё время»: pass `--all` and include cold history.
- Never silently truncate history to 10. UI pages 10 rows; clearly labelled totals cover the entire selected history or date range, independently of the visible page. Changing pages closes details from the previous page. An explicitly requested period limits the browsable history to that selection.

```
python <skill>/scripts/control_unit_report.py --root <project> --fragment --output <task-output>/progress.html
python <skill>/scripts/control_unit_report.py --root <project> --all --fragment --output <task-output>/progress.html
python <skill>/scripts/control_unit_report.py --root <project> --since 2026-10-01 --until 2026-10-20 --fragment --output <task-output>/progress.html
```

Use the host's supported inline HTML display (or the available visualize skill) to show the resulting fragment. Without an interactive host, provide the standalone HTML (omit `--fragment`); do not promise a live sidebar or a new side-chat. Title/result buttons show stored texts; they do not call the model. Answering a subsequent user question is ordinary model work and consumes tokens.

Date filters select CUs whose lifetime overlaps the requested dates. In this first version usage is **the lifetime cost of the selected CUs**, explicitly labelled, not period-sliced costs. Do not describe it as tokens spent only inside the date range. All-time includes all recorded CU history, not undocumented historical work. If empty, show that CU recording has not begun; do not invent CUs from turns or import legacy science silently.

## Bounded active memory

CU events are `kind=artifact`, `payload.type=control_unit_event` envelopes in existing EVIDENCE. Immutable old batches move to `archive/evidence-store/*.jsonl` after verification. Explicit evidence lookup and CU reporting resolve cold history; normal memory queries remain hot-only. Archive files are cold storage, not another current memory catalogue. Never load the entire archive into the model context.

Defaults: at most 300 hot CU events / 256 KiB, retired in batches to 75% of the caps. `.cd5/config.json` may override `control_units.keep_active_events` / `max_active_bytes`. Other evidence is not automatically moved by a CU write. A full evidence compaction is explicit, lossless and preserves references; do not run it on an existing project as an installation side effect.

`cu_archive.py --root <project> budget` checks all five active files against configurable byte budgets (`memory_limits_bytes`). `compact` defaults to dry-run; `--apply` executes a verified archive move. OUTLINE/CHECKPOINT/current knowledge/attention must not be blindly truncated: their size alerts require the owner to summarize/archive with semantic review. This version enforces CU hot-event bounds automatically and diagnoses other files; it does not enforce hard bounds on arbitrary writes by other tools. Cold history on disk necessarily grows if all-time history is retained.

## Readable report layout

The overview fits the containing browser panel. Use short row ordinals and compact dates; retain complete CU IDs in readable details. Keep main plan/actual cells numeric and short, with full unknown reasons and participant measurements available on click. Long task/result text opens in details. Narrow panels use stacked rows; expanded teams and details must also fit without horizontal page scrolling. Keep operational checkpoint details collapsed initially so they do not push the overview off screen.

When the team total is unknown but the sole HQ has verified measured WU, show that amount as HQ usage in the compact row, explicitly separate from the unknown team total. Use a partial/lower-bound marker for unfinished coverage; do not add child counters merely to fill the main cell.

## Five-hour quota view and agent work

The same Progress Report offers a five-hour view aligned to observed native Codex quota resets. Derive each boundary from its saved 300-minute window and reset timestamp, not fixed wall-clock bins or backwards extrapolation from the current reset. Show exact overlapping reset variants and missing boundaries explicitly. This view covers only verified project observations, not all account activity or a subscription percentage. Date filters select request-observation timestamps in the report timezone, without prorating request costs.

Show individual Planner, Executor, Reviewer and other assigned roles, their measured token categories and WU. Aggregate only disjoint observations within the same verified native UUID/window; never add parent/child actors without independent-scope proof. Saved spawn/followup briefs and final agent answers explain what was assigned and returned, with source witnesses. Do not generate another model narrative, infer roles from nicknames, or treat a CU-level result as the agent's answer. Unassigned measurements and rejected ambiguous selections remain visible with diagnostics. UI labels are Agents and План / Факт; HQ is displayed as Planner without rewriting stored role IDs.
