> **Historical/diagnostic reference, superseded for active CD5 continuation.**
> Current architecture is [one shared Continuator and CD5 Goal](file-continuation.md).
> Native agent Goal is not a CD5 driver. Do not activate legacy wakeups or follow
> old native-only instructions below for current HQs; preserve the historical evidence.

# Planner execution control

For ordinary continuation, prefer the application's [native Goal](native-goal.md)
after user authorization. This external supervisor is an optional diagnostic or
recovery component, not the default replacement for native continuation. If
CHECKPOINT.native_goal.driver is `native`, it never dispatches an external wake;
even a missing/paused native Goal requires reconciliation, not a silent fallback.

`scripts/planner_control.py` implements a local deterministic supervisor. It does
not call a model to check time, quota or activity. The host integration is an
explicit adapter, not an hourly message or an agent automation. Installing CD5
does not enable unattended work or install a startup task.

Two operational files live beside CHECKPOINT (they are not scientific memory):

- `PLANNER_STATE.json`: atomic current state, owner, pending action, authorization,
  resume time, activity lease and recovery count.
- `PLANNER_EVENTS.jsonl`: fsynced append-only transition journal with timestamps,
  reason, source and the resulting state snapshot. Lease refreshes are explicit;
  ordinary watchdog checks do not append events.

States are STOP, RUNNING, READY, WAIT_QUOTA, WAIT_WORKER, WAIT_USER, COMPLETE,
DISPATCHING and BLOCKED. STOP/WAIT_USER/COMPLETE never wake automatically. A user
STOP in CHECKPOINT overrides operational state. Neither this state file nor an
adapter grants scientific authorization or replaces the frozen-protocol gate.

## Commands

Use the installed Python and CD5 paths for your machine:

```text
python <skill>/scripts/planner_control.py --root <project> init --owner-thread <actual-id>
python <skill>/scripts/planner_control.py --root <project> status
python <skill>/scripts/planner_control.py --root <project> set --state READY --reason "User authorized continuation" --source user --authorized --next-action "Review saved result"
python <skill>/scripts/planner_control.py --root <project> set --state WAIT_QUOTA --reason "Quota admission closed" --authorized --next-action "Review saved result" --reset-at <observed-unix-reset>
python <skill>/scripts/planner_control.py --root <project> heartbeat
python <skill>/scripts/planner_control.py --root <project> tick --adapter <adapter-argv.json>
python <skill>/scripts/planner_control.py --root <project> watch --adapter <adapter-argv.json>
```

Initialization refuses existing files and starts STOP. A reset gets a 60-second
safety margin; no imaginary recurring five-hour windows are generated. Planner
records RUNNING and refreshes its lease at bounded work boundaries (default lease
15 minutes); it records a waiting/completed state before ending. A live native
active status always blocks recovery even when the lease expires. The supervisor
may recover a crashed idle Planner once; another crash becomes BLOCKED. A normal
lease refresh does not reset the recovery count. Only explicit user reconciliation
clears it. After reboot, restart the same `watch` command through a separately
authorized OS startup service. No active agent is needed while waiting.

## Host adapter contract

`codex_host_probe.py --codex <executable> [--socket <existing-control-socket>]`
is a bundled read-only diagnostic adapter. It connects only through `app-server
proxy`; it never starts an independent server. It checks native thread metadata
and account limits, but returns `wake_supported=false`: the installed protocol
does not establish atomic conditional-idle delivery or complete worker coverage.
An unavailable Desktop control socket is an explicit blocker, not permission to
start a second server or infer idle from history.

`scripts/install_planner_watch.ps1 -Project <root> -Python <python.exe> -Adapter
<argv.json>` registers and starts a single Windows logon task, using sibling
`pythonw.exe`, no stored password and no elevated task principal. Existing tasks
are never overwritten. `-Remove` unregisters the named task. The watchdog survives
agent turns and starts on the next user logon after reboot; it cannot run before
login or while the computer is off. Checks are local and do not launch model turns.

### Canonical checkpoint integration

Once control files exist, `project_memory.py write-checkpoint` automatically
mirrors the HQ lifecycle record. Example (synthetic):

```json
{"planner_control":{"state":"WAIT_QUOTA","reason":"Five-hour quota boundary","authorized":true,"reset_at":1800000000},"next_action":{"kind":"review_saved_result"}}
```

This is an excerpt, not a complete valid CHECKPOINT. Every opted-in HQ save must
declare the state and reason. The operational fingerprint binds admission to the
exact checkpoint; an unsynchronized edit blocks continuation. STOP, completion,
owner changes and CD5 off override the lifecycle record. The integration never
creates files or arms a project automatically. Control-file write failure is
reported even if the canonical checkpoint was already saved.

Use `reconcile` after a journal/state mismatch to preserve history and recover the
last complete journal snapshot as BLOCKED. Damaged/truncated journal lines require
manual inspection. Recovery never repeats a dispatch or clears STOP; a later
explicit user reconciliation is required before rearming.

The adapter configuration is a JSON argv array, e.g. a synthetic example
`["python", "host_adapter.py"]`. Execution uses no shell, a 30-second timeout and
stdin/stdout JSON. The adapter must use a supported host API; scraped journal
timestamps, cached quota and a PID alone are not authoritative idle checks.

For `operation=probe`, with `root` and `owner_thread_id`, return:

```json
{"observed_at": 1800000000, "owner_thread_id": "synthetic-owner", "planner_status": "idle", "workers_idle": true, "quota": {"ordinary_allowed": true, "used_percent": 20, "window_minutes": 300}}
```

This example is synthetic. Observation must be at most 60 seconds old, owner must
match, all project workers must be proven idle, ordinary usage must be allowed,
and the 300-minute window must be below 90%. Unknown fields block admission.
The probe must perform no model calls.

For `operation=wake`, the request also contains `dispatch_id`, `expected_idle`,
`next_action` and a bounded recovery `message`. The host must atomically recheck
owner/idle/STOP and deduplicate the dispatch ID before sending exactly one message
to the existing owner. It returns `{"accepted":true,"dispatch_id":"<same-id>"}`
only after acceptance. An adapter that cannot guarantee this must reject the wake.

**There is no bundled Codex desktop adapter:** tool access inside an agent turn
is not an unattended host API. Without a suitable adapter the controller remains
fail-closed and reports `host adapter not configured`. Do not claim unattended
desktop continuation is active merely because the supervisor is installed.

## Crash and ambiguity handling

An OS-backed lock serializes ticks and state writers, including multiple watchdog
processes. The durable DISPATCHING transition precedes sending. Delivery timeout
or process death in this interval never leads to a blind resend: DISPATCHING
requires inspection and explicit user reconciliation. Thus ambiguous delivery
favors stopping over duplicate work; exactly-once delivery across a network crash
requires host idempotency and cannot be promised by a local JSON file alone.

Journal is written before atomic state replacement. Missing/corrupt files or a
journal/state mismatch fail closed; preserve both files and reconcile the final
journal snapshot after checking host activity. Do not delete a lock or fabricate
RUNNING to recover. A stopped watchdog emits an error to stderr for its OS service
to surface; this release does not provide an external notification channel.
