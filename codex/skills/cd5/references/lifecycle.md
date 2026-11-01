# CD5 lifecycle

For continuous HQ work, follow [Continuator и приостановка HQ](file-continuation.md).
The hidden service is per user OS login and processes explicitly enrolled HQs one
at a time. It reads only the saved continuation flags, known busy state, and fresh
quota gate, then sends at most one continuation to the current planner chat found
through `CHECKPOINT.owner.thread_id`. The agreed CD5 tasks and milestones are the
project goal; the application's native agent Goal is not a CD5 driver. Do not
create, resume, update, or clear native Goal state, and do not add another
continuation mechanism. Each HQ retains its five canonical memory files.

The user owns continue_HQ. Change it only for explicit Continuator enable/disable.
HQ owns suspend_HQ: create it only at whole-plan completion or an evidenced mandatory user/system requirement blocking all remaining permitted work. See [HQ authority](hq-authority.md).
User start/continue removes it; Interrupt and user stop create it. At quota>=90
change neither file; checkpoint and finish the turn. Never poll/sleep until reset.
Preserve other HQs' flags, permissions, budgets and native Goal history.

The separate legacy [Planner control](planner-control.md) integration is not a
second driver for an HQ enrolled in the continuation service. For that workflow,
the service admission gates and user-owned Continuator enable flag in file-continuation.md
control continuation.

At the start and before each substantive stage, read project instructions, OUTLINE, CHECKPOINT, and only the relevant linked KNOWLEDGE, EVIDENCE, and ATTENTION records. Establish the current owner, goal, next useful action, STOP, and applicable limits. Read fresh quota and native activity status where the project requires them. Unknown quota or activity is not clearance.

An explicit user STOP remains in force until the user resumes it. Turning CD5 off pauses CD5 activity; it does not erase the goal, change STOP, or alter MAC. Turning CD5 on resumes only within existing scope and authorization. A memory change alone does not expand the user task. The assigned plan authorizes HQ to choose and internally approve its next useful runs and repair versions.

For CD5 off, save CHECKPOINT.cd5.enabled=false and create suspend_HQ. Do not
alter continue_HQ. CD5 on does not clear suspension or enable Continuator.
Only explicit user HQ start/continue clears suspension. Continuator enable and
HQ start are independent commands. CD5 status reports both actual flags.

When a project uses the 90% quota gate, read the fresh five-hour (300-minute) account window, not the weekly window or context occupancy, before work and between bounded stages. At usedPercent >= 90, stop admitting substantive work and finish the HQ turn after a minimal durable checkpoint and final status. Missing quota is not clearance. This is a terminal boundary for the current turn, not an instruction to keep the chat running until reset.

Save the observed percentage, window and reset time when available, pending work, known active-worker state and the resume condition in CHECKPOINT. Preserve the owner, user STOP and scientific budgets; quota exhaustion does not mean project completion, CD5 off or permission to rotate/archive the HQ. Do not launch a successor or worker, start another stage, poll repeatedly, sleep until reset, or keep a wait loop alive. Do not create a wakeup unless separately authorized. Already admitted calls may finish; retain their artifacts and defer substantive review until recovery rather than spending the remaining quota. If activity is unknown, record it for the next admission check instead of waiting indefinitely in this turn.

Return a concise final status that the HQ has stopped at the quota boundary and what remains. A later independently authorized invocation may resume only with fresh ordinary usage allowed, five-hour usage below 90%, no user STOP and activity checks clear. Existing authorized wakeups may provide that invocation; do not invent reset IDs or schedules. The skill enforces an agent decision at observable boundaries, not provider-level interruption of an in-flight model/tool call.

For controlled work HQ records and internally accepts a versioned protocol: question, cases, conditions, criteria, internal budget and expected decisions. The executor follows that version and returns changes to HQ. HQ can accept a new version within the assigned plan without human reapproval. Keep old versions, attempts and results intact; never describe historical records as prospectively frozen. Direct user constraints and mandatory system permissions remain binding.

At a user-facing work boundary, use the current Control Unit as the reporting group; do not create a start/finish task record for every internal action. Reuse any existing task records and link them to the CU. Read [control units](control-units.md) for recording and Progress Report invocation. Keep measured time and token counts with their source; missing values remain unknown. Do not infer active time from elapsed time, combine parent and child counts with overlapping scope, or treat completion as scientific acceptance.

Continue useful authorized branches when one branch is blocked. Ordinary stop boundaries are quota>=90 and whole-plan completion. Honor direct user STOP and actual user/system requirements. Unknown activity requires HQ inspection to avoid duplicates; inspect it or continue another permitted branch. A technical fault or internal allocation exhaustion is an HQ repair/revision decision, not a human permission gate.

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
answer only when a cited actual user/system requirement demands it for all remaining useful permitted work; an agent-created decision/wait_user label is insufficient.
Then create suspend_HQ with the reason in CHECKPOINT; do the same when all
currently authorized work is complete. Do not alter continue_HQ. Quota closure
changes neither flag: the service automatically resumes below90 if not suspended.

Before advancing the plan, follow [outline](outline.md). After accepted significant results or scope changes, reconcile affected risks, dependencies, milestone outcomes and the active plan; a completed CU does not itself close a milestone. Preserve earlier criteria and outcomes as history.
