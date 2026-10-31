> **Historical/diagnostic reference, superseded for active CD5 continuation.**
> Current architecture is [one shared Continuator and CD5 Goal](file-continuation.md).
> Native agent Goal is not a CD5 driver. Do not activate legacy wakeups or follow
> old native-only instructions below for current HQs; preserve the historical evidence.

# Unified native continuation admission

`continuation_admission.decide(checkpoint, observation, now)` is a pure decision
function. It performs no model calls, Goal writes, dispatch, polling or service
installation. `allowed=true` authorizes only the selected native driver to remain
eligible; `external_dispatch_allowed` is always false. It cannot resume a paused
Goal or prove that the application actually continued.

Required checkpoint inputs are explicit owner thread/generation, user STOP,
CD5 enabled, waiting-user and goal-complete booleans, continuation authorization,
a useful next action and native Goal driver. Existing checkpoints missing these
fields are denied; this function never fills them in or grants authorization.

The observation must match the exact checkpoint fingerprint and owner generation.
Activity and quota must be at most5 seconds old with no future timestamps. The
root must be idle by default, with no pending input; the correct ordinary300-minute quota
must be below90, every known worker must have a fresh idle read, and the caller
must separately establish full worker coverage. Goal must be active, another
driver absent and this boundary not already consumed. Unknown values deny.

For admission of useful work by the already-running owner, an explicit
`execution_context=owner_turn` accepts active status only when caller identity,
expected turn ID and the host's actual inProgress turn all match, with no active
waiting flags. It authorizes only that same owner's work, never an external wake.
An arbitrary active thread or completed/different turn is rejected.

A live current-owner integration used direct collaboration.list_agents (only
the root was present), Desktop read_thread, get_goal and fresh account usage.
The detailed native planner returned continue with external dispatch forbidden.
This establishes one owner admission, not an unattended event transport or a
guarantee about participants not covered by the current native team. A standalone
hook cannot manufacture that direct collaboration snapshot.

The caller is responsible for obtaining actual same-Desktop observations and
verifying their provenance. A coverage receipt ID is only an audit reference;
inventing one or copying fixture booleans is not coverage. Worker event loss,
restart baseline and races between observation and a subsequent action remain
integration requirements, not capabilities proven by these unit tests.

The existing `native_goal.py` planner accepts an optional `continuation` object
inside its observations JSON. A checkpoint with the explicit boolean
`continuation_admission_required=true` requires that object before returning
`continue` for an existing active Goal. Its quota data/time must equal the
planner's separate quota observation. Missing details cannot fall back to the
legacy generic workers_idle flag; malformed enablement settings also deny.
Goal creation, pause authority and preservation of stopped Goals retain their
existing lifecycle contract. This flag is not enabled in user projects by
installation. Before enabling it, supply an actual complete observation source.

This planner integration is not yet wired into a production Desktop event path.
The working HQ retains native Goal only. The trusted technical Stop trial and
event recorder remain distinct bounded tests; they never dispatch into the HQ.
Automatic quota resume and application/computer restart recovery are unverified.

## Observed native prompt-hook limitation

In a controlled Windows Desktop trial on30Oct2026, a temporary native Goal made
two natural turns and completed through the native tool. Both turns emitted Stop,
but neither emitted UserPromptSubmit. A subsequent actual UI message in the same
chat did emit UserPromptSubmit under the same trusted recorder definition. Thus
the negative native result had a positive control: the recorder was functional.

Do not use UserPromptSubmit as a pre-model gate for automatic native Goal on that
observed installation. The callback can protect an ordinary user prompt without
covering native continuation. This is an observed installation limit, not a
claim about every future Codex release. PreToolUse occurs after a model has
already requested a tool; SessionStart is not established as a per-continuation
callback. Neither is a proven substitute for the missing native pre-model gate.

The owner-run admission implemented here remains useful for denying substantive
work at the beginning of an admitted model turn. It does **not** guarantee zero
model calls while native Goal remains active under externally changed conditions.
Use the explicitly authorized native pause policy at actual waiting boundaries;
never run a model quota-polling loop. A separate client-owned runtime would be a
different explicitly authorized mode, not a silent second server controlling a
Desktop-owned Goal. Do not bypass the native Goal tool's lifecycle contract.
