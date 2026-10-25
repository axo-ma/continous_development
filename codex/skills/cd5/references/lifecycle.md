# CD5 lifecycle

For projects opted into [Planner control](planner-control.md), every HQ checkpoint
must include `planner_control` with explicit `state`, `reason` and `authorized`.
Use RUNNING at admission/bounded work boundaries, WAIT_QUOTA with observed
`reset_at` (Unix seconds) before quota exit, WAIT_WORKER when waiting, WAIT_USER
for a human decision and COMPLETE only after verification. The memory API mirrors
these into operational state/events automatically. Missing lifecycle records block
an opted-in controller; they never imply runnable work. Keep `next_action` useful
and preserve STOP, protocol and budget gates. Do not refresh a RUNNING lease while
idle or start model turns merely to refresh it.

At the start and before each substantive stage, read project instructions, OUTLINE, CHECKPOINT, and only the relevant linked KNOWLEDGE, EVIDENCE, and ATTENTION records. Establish the current owner, goal, next useful action, STOP, and applicable limits. Read fresh quota and native activity status where the project requires them. Unknown quota or activity is not clearance.

An explicit user STOP remains in force until the user resumes it. Turning CD5 off pauses CD5 activity; it does not erase the goal, change STOP, or alter MAC. Turning CD5 on resumes only within existing scope and authorization. A workflow or memory change never authorizes a new run.

For CD5 off, save CHECKPOINT.cd5.enabled=false through the memory API and pause only existing authorized CD5 wakeups when host tools are available, recording their prior states. On CD5 on, save enabled=true without clearing user_stop; restore only previously authorized wakeups in their recorded prior state, subject to STOP and current permission. Do not create schedules or activate a previously paused schedule merely because CD5 was installed. CD5 status reports actual enabled/STOP/owner/next-action and known wakeup states, leaving missing information unknown.

When a project uses the 90% quota gate, read the fresh five-hour (300-minute) account window, not the weekly window or context occupancy, before work and between bounded stages. At usedPercent >= 90, stop admitting substantive work and finish the HQ turn after a minimal durable checkpoint and final status. Missing quota is not clearance. This is a terminal boundary for the current turn, not an instruction to keep the chat running until reset.

Save the observed percentage, window and reset time when available, pending work, known active-worker state and the resume condition in CHECKPOINT. Preserve the owner, user STOP and scientific budgets; quota exhaustion does not mean project completion, CD5 off or permission to rotate/archive the HQ. Do not launch a successor or worker, start another stage, poll repeatedly, sleep until reset, or keep a wait loop alive. Do not create a wakeup unless separately authorized. Already admitted calls may finish; retain their artifacts and defer substantive review until recovery rather than spending the remaining quota. If activity is unknown, record it for the next admission check instead of waiting indefinitely in this turn.

Return a concise final status that the HQ has stopped at the quota boundary and what remains. A later independently authorized invocation may resume only with fresh ordinary usage allowed, five-hour usage below 90%, no user STOP and activity checks clear. Existing authorized wakeups may provide that invocation; do not invent reset IDs or schedules. The skill enforces an agent decision at observable boundaries, not provider-level interruption of an in-flight model/tool call.

For scientific or similarly controlled work, use an accepted frozen protocol that states the question, cases, fixed conditions, criteria, budget, and expected decisions. The executor works within it and records deviations and limits. A change to protocol scope returns to the accountable owner and applicable approval process; do not silently revise a frozen protocol or treat an imported historical protocol as prospectively frozen.

At a user-facing work boundary, use the current Control Unit as the reporting group; do not create a start/finish task record for every internal action. Reuse any existing task records and link them to the CU. Read [control units](control-units.md) for recording and Progress Report invocation. Keep measured time and token counts with their source; missing values remain unknown. Do not infer active time from elapsed time, combine parent and child counts with overlapping scope, or treat completion as scientific acceptance.

Continue useful authorized branches when one branch is blocked. Wait only when STOP, quota, unavailable or unknown activity, or exhaustion of useful permitted steps prevents progress. Save the concrete blocker and resume condition, and show a genuine human decision when required.

Before advancing the plan, follow [outline](outline.md). After accepted significant results or scope changes, reconcile affected risks, dependencies, milestone outcomes and the active plan; a completed CU does not itself close a milestone. Preserve earlier criteria and outcomes as history.
