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
root must be idle with no pending input, the correct ordinary300-minute quota
must be below90, every known worker must have a fresh idle read, and the caller
must separately establish full worker coverage. Goal must be active, another
driver absent and this boundary not already consumed. Unknown values deny.

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
