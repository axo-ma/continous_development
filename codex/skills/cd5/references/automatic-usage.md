# Automatic factual usage

Use automatic usage for ordinary CU accounting. No model call, reporting agent, background wakeup or per-turn task record is required. The owner still chooses meaningful CU boundaries; code cannot infer the user's intended work granularity from a transcript. The normal begin command requires a prospective forecast range or an explicit short reason why a defensible forecast is unavailable; see [WU budgets](wu-budgets.md). It requires no WU limit.

## Owner actions

At the beginning of a meaningful CU, reuse its existing title/goal:

```
python <skill>/scripts/control_units.py --root <project> begin --cu <stable-id> --title "Existing work title" --caller-thread <actual-owner-thread> --forecast-low 3 --forecast-high 6
```

Before every substantive continuation, check the active CU's saved plan with `summary`. A reason recorded only in CHECKPOINT or an executor brief does not populate the CU report. If an older open CU has no forecast, record a current prospective revision or its explicit unknown reason before further work; never label that revision as an original forecast. Use `budget --cu <id> --caller-thread <owner> --event-id <stable-id> --reason "Review of remaining scope" --forecast-unknown-reason "Why the remaining scope cannot yet be estimated"`, or supply a current forecast range instead. The owner writes this metadata; another reporting chat does not impersonate it.

After a successful worker launch, the owner registers the explicit role once with `participant --cu <id> --caller-thread <owner> --agent-path /root/<exact-task-name> --role executor` (or helper/reviewer/consultant as actually assigned). The command resolves a unique verified native UUID using the exact task path and immediate parent; for nested work pass `--parent <actual-parent-thread>`. Missing/ambiguous native identities are errors to resolve, never fabricated IDs. On worker reuse retain its bounded assignment under the CU; a lifetime worker total is not the assignment's usage.

At completion, reuse the existing short result:

```
python <skill>/scripts/control_units.py --root <project> finish --cu <stable-id> --result "Existing short outcome" --caller-thread <actual-owner-thread>
```

Optional `--source` records an existing brief/result path without reading it. The fuller `record` API remains available for pause/resume, existing detailed text and explicit participants. Do not duplicate a brief, create a CU for each tool call or ask an executor to write an additional report. These two semantic marks replace manual source-file/ordinal mapping in the normal path. Retries retain the original anchor and do not add events.

The tool captures the actual owner turn automatically in `auto_anchor` on new, non-historical CU open/status events. A historical `at` is not used to invent an anchor. At the next progress read, the code discovers verified native journals, attributes bounded owner turns, reads cumulative token counters, derives elapsed turn time and feeds the existing WU estimator. It does not persist a second measurement event on every read. Canonical CU events and original journals remain authoritative; rendering does not change them.

## Resolution and limits

- `cu_auto_telemetry.py` uses `.cd5/config.json` → `control_units.telemetry.session_roots` when supplied; otherwise both `sessions` and `archived_sessions` under the host's `CODEX_HOME` or home `.codex`. Archival relocation retains attribution only when the unique session identity and saved start/prefix hashes still match; duplicate identities remain unknown. A host without accessible native journals still shows CU metadata with unknown usage. `control_units.telemetry.enabled=false` disables this adapter only.
- Attribution is at whole owner-turn granularity. The turn opening a CU and its closing turn are included; two different CUs claiming the same turn are ambiguous, not split by elapsed time. New non-historical opens and resumes (`status=open`) with an observed anchor reject a turn already marked by another CU, before writing an event; continue the existing CU or open/resume the next in a new user turn. Idempotent retries retain the original anchor. This guard does not reconstruct historical overlapping turns or promise measurement when native journals are unavailable.
- An open/closing turn may still be writing counters. Verified deltas through the last observed snapshot are visible as partial participant usage, with its observation time, until a later report read sees completion. No model call is needed to display existing measurements. Missing measured duration stays separate from valid token counts. Child discovery uses verified native ancestry and observed parent spans, including bounded open turns and reused-worker followups; work beyond the last observed parent boundary remains incomplete. Logical completion and final usage availability are separate; do not wake a model solely to settle a counter.
- Identity comes from verified `session_meta.id`, not a filename or `session_id`. Raw journal records are never rewritten. Saved anchor positions/hashes must still match. Missing baselines, counter resets, truncated sources, contradictory values and unsplit model changes remain incomplete/unknown.
- A fresh native session can prove its initial baseline from the first cumulative snapshot equalling that snapshot's last-request usage, under the adapter's cumulative/last-request counter contract and an intact source prefix. Record that derived-baseline witness; a first nonzero snapshot alone never proves zero.
- Agents require verified parent/spawn evidence and unambiguous CU attribution. Roles are not guessed from names. Reusing a child across CUs must not duplicate counters. Explicit participant registration remains available for otherwise ambiguous assignments.
- An active parent span ends at its latest observed native counter snapshot, never at wall-clock time. Verified child turns inside that span are discoverable before the parent finishes, including followups to an earlier child. A child extending beyond the observed span stays incomplete.
- Register a role using the exact canonical task path (synthetic example): `python <skill>/scripts/control_units.py --root <project> participant --cu <id> --caller-thread <owner> --agent-path /root/worker --role executor`. Parent defaults to the caller; `--parent`, `--name` and an actual native `--thread` are optional. Without `--thread`, both native metadata path fields and both parent IDs must match exactly one session; otherwise the command fails before writing and asks to retry after the header exists. The `record` participant API accepts the same `agent_path` with omitted `thread_id`. It records the resolved native UUID, never a fabricated thread ID. Existing safe symbolic registrations with an explicit exact path may also resolve read-only; task-name fragments and nicknames never establish roles or identity.
- Parent/child ancestry alone does not prove independently scoped counters. A project may reference an existing verified witness once via `control_units.telemetry.independent_scope_evidence`; the collector validates that EVIDENCE reference. Never create a fictitious witness to make a total appear. Without proof, participant measurements remain useful but the team total is partial/unknown. This is not a per-CU bookkeeping step.
- Existing explicit measurements are preserved instead of counted again. Manual `collect` remains an exception for unsupported sources or reviewed historical reconstruction.

Report generation and local interactions use no LLM. The chat turn invoking a command and the two short owner marks still have their usual orchestration cost. No platform turn-end hook is installed; this is automatic collection on progress reads, not continuous live refresh.
