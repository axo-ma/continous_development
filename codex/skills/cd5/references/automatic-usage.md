# Automatic factual usage

Use automatic usage for ordinary CU accounting. No forecast, model call, reporting agent, background wakeup or per-turn task record is required. The owner still chooses meaningful CU boundaries; code cannot infer the user's intended work granularity from a transcript.

## Owner actions

At the beginning of a meaningful CU, reuse its existing title/goal:

```
python <skill>/scripts/control_units.py --root <project> begin --cu <stable-id> --title "Existing work title" --caller-thread <actual-owner-thread>
```

At completion, reuse the existing short result:

```
python <skill>/scripts/control_units.py --root <project> finish --cu <stable-id> --result "Existing short outcome" --caller-thread <actual-owner-thread>
```

Optional `--source` records an existing brief/result path without reading it. The fuller `record` API remains available for pause/resume, existing detailed text and explicit participants. Do not duplicate a brief, create a CU for each tool call or ask an executor to write an additional report. These two semantic marks replace manual source-file/ordinal mapping in the normal path. Retries retain the original anchor and do not add events.

The tool captures the actual owner turn automatically in `auto_anchor` on new, non-historical CU open/status events. A historical `at` is not used to invent an anchor. At the next progress read, the code discovers verified native journals, attributes bounded owner turns, reads cumulative token counters, derives elapsed turn time and feeds the existing WU estimator. It does not persist a second measurement event on every read. Canonical CU events and original journals remain authoritative; rendering does not change them.

## Resolution and limits

- `cu_auto_telemetry.py` uses `.cd5/config.json` → `control_units.telemetry.session_roots` when supplied; otherwise the host's `CODEX_HOME/sessions` or home `.codex/sessions`. A host without accessible native journals still shows CU metadata with unknown usage. `control_units.telemetry.enabled=false` disables this adapter only.
- Attribution is at whole owner-turn granularity. The turn opening a CU and its closing turn are included; two different CUs claiming the same turn are ambiguous, not split by elapsed time. Prefer a CU boundary between user-facing work stages rather than repeatedly switching CUs inside one turn.
- A closing turn may still be writing counters. It stays provisional until a later report read sees completion. Logical completion and final usage availability are separate; do not wake a model solely to settle a counter.
- Identity comes from verified `session_meta.id`, not a filename or `session_id`. Raw journal records are never rewritten. Saved anchor positions/hashes must still match. Missing baselines, counter resets, truncated sources, contradictory values and unsplit model changes remain incomplete/unknown.
- A fresh native session can prove its initial baseline from the first cumulative snapshot equalling that snapshot's last-request usage, under the adapter's cumulative/last-request counter contract and an intact source prefix. Record that derived-baseline witness; a first nonzero snapshot alone never proves zero.
- Agents require verified parent/spawn evidence and unambiguous CU attribution. Roles are not guessed from names. Reusing a child across CUs must not duplicate counters. Explicit participant registration remains available for otherwise ambiguous assignments.
- Parent/child ancestry alone does not prove independently scoped counters. A project may reference an existing verified witness once via `control_units.telemetry.independent_scope_evidence`; the collector validates that EVIDENCE reference. Never create a fictitious witness to make a total appear. Without proof, participant measurements remain useful but the team total is partial/unknown. This is not a per-CU bookkeeping step.
- Existing explicit measurements are preserved instead of counted again. Manual `collect` remains an exception for unsupported sources or reviewed historical reconstruction.

Report generation and local interactions use no LLM. The chat turn invoking a command and the two short owner marks still have their usual orchestration cost. No platform turn-end hook is installed; this is automatic collection on progress reads, not continuous live refresh.
