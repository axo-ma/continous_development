# CD5 lifecycle

For continuous HQ work, follow [Stop Goal / Continue Goal](file-continuation.md).
The hidden service is per user OS login and processes explicitly enrolled HQs one
at a time. It reads only the saved continuation flags, known busy state, and fresh
quota gate, then sends at most one continuation to the current planner chat found
through `CHECKPOINT.owner.thread_id`. The agreed CD5 tasks and milestones are the
project goal; the application's native agent Goal is not a CD5 driver. Do not
create, resume, update, or clear native Goal state, and do not add another
continuation mechanism. Each HQ retains its five canonical memory files.

The HQ owns its continuation flags and project state. Remove Continue when the
expected work is complete, when a user answer is required, or when quota reaches
90%. Save a concise checkpoint and finish the turn at that boundary; do not poll,
sleep, or launch a successor to wait out quota. Preserve STOP, protocol, budgets,
owner, and other HQs' memory. Never change another HQ's flags or native Goal
history.

The separate legacy [Planner control](planner-control.md) integration is not a
second driver for an HQ enrolled in the continuation service. For that workflow,
the service admission gates and HQ-owned Continue flag in file-continuation.md
control continuation.

At the start and before each substantive stage, read project instructions, OUTLINE, CHECKPOINT, and only the relevant linked KNOWLEDGE, EVIDENCE, and ATTENTION records. Establish the current owner, goal, next useful action, STOP, and applicable limits. Read fresh quota and native activity status where the project requires them. Unknown quota or activity is not clearance.

An explicit user STOP remains in force until the user resumes it. Turning CD5 off pauses CD5 activity; it does not erase the goal, change STOP, or alter MAC. Turning CD5 on resumes only within existing scope and authorization. A workflow or memory change never authorizes a new run.

For CD5 off, save CHECKPOINT.cd5.enabled=false and remove Continue Goal; leave
Stop Goal intact. CD5 on saves enabled=true but does not clear Stop or create
Continue automatically. Only explicit user Continue Goal reopens continuation.
Do not restore legacy wakeups or create a second driver. CD5 status reports the
actual flags, owner, next action and shared service state; unknown remains unknown.

When a project uses the 90% quota gate, read the fresh five-hour (300-minute) account window, not the weekly window or context occupancy, before work and between bounded stages. At usedPercent >= 90, stop admitting substantive work and finish the HQ turn after a minimal durable checkpoint and final status. Missing quota is not clearance. This is a terminal boundary for the current turn, not an instruction to keep the chat running until reset.

Save the observed percentage, window and reset time when available, pending work, known active-worker state and the resume condition in CHECKPOINT. Preserve the owner, user STOP and scientific budgets; quota exhaustion does not mean project completion, CD5 off or permission to rotate/archive the HQ. Do not launch a successor or worker, start another stage, poll repeatedly, sleep until reset, or keep a wait loop alive. Do not create a wakeup unless separately authorized. Already admitted calls may finish; retain their artifacts and defer substantive review until recovery rather than spending the remaining quota. If activity is unknown, record it for the next admission check instead of waiting indefinitely in this turn.

Return a concise final status that the HQ has stopped at the quota boundary and what remains. A later independently authorized invocation may resume only with fresh ordinary usage allowed, five-hour usage below 90%, no user STOP and activity checks clear. Existing authorized wakeups may provide that invocation; do not invent reset IDs or schedules. The skill enforces an agent decision at observable boundaries, not provider-level interruption of an in-flight model/tool call.

For scientific or similarly controlled work, use an accepted frozen protocol that states the question, cases, fixed conditions, criteria, budget, and expected decisions. The executor works within it and records deviations and limits. A change to protocol scope returns to the accountable owner and applicable approval process; do not silently revise a frozen protocol or treat an imported historical protocol as prospectively frozen.

At a user-facing work boundary, use the current Control Unit as the reporting group; do not create a start/finish task record for every internal action. Reuse any existing task records and link them to the CU. Read [control units](control-units.md) for recording and Progress Report invocation. Keep measured time and token counts with their source; missing values remain unknown. Do not infer active time from elapsed time, combine parent and child counts with overlapping scope, or treat completion as scientific acceptance.

Continue useful authorized branches when one branch is blocked. Wait only when STOP, quota, unavailable or unknown activity, or exhaustion of useful permitted steps prevents progress. Save the concrete blocker and resume condition, and show a genuine human decision when required.

An intermediate result, a finished CU, or an unavailable optional enhancement is
not itself a reason to stop the project. Before ending useful work,
identify the next already-authorized action and execute it when possible. Do not
substitute a promise to continue for available work. In particular, an unverified
pre-model native callback does not block ordinary authorized owner-run work with
its existing admission checks; retain that limitation separately.

If one branch needs human input, first check independent ready actions. The planner
can recommend `select_next_action` from explicitly authorized, useful,
unblocked `ready_actions` requiring no human input. Save that selection and repeat
normal admission before execution; selection itself grants no run permission.
STOP, quota and actual unknown activity remain controlling. Pause for a human
answer only when it is required for all remaining useful permitted work. Keep
Continue active at ordinary useful-work boundaries when permitted work remains.
Remove it when a user decision is required or admission is closed; after STOP or
quota recovery, an explicit user Continue Goal must reopen it.

Before advancing the plan, follow [outline](outline.md). After accepted significant results or scope changes, reconcile affected risks, dependencies, milestone outcomes and the active plan; a completed CU does not itself close a milestone. Preserve earlier criteria and outcomes as history.
