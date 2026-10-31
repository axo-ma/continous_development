# CD5 owner rotation

The continuation service routes each enrolled HQ to the current planner chat from
`CHECKPOINT.owner.thread_id`; it does not rotate owners or change ownership. Do
not use native Goal as a handoff mechanism. A user-authorized handoff is one
controlled ownership change: confirm the old owner is safely stopped and known
idle, then have the successor read project instructions, OUTLINE, CHECKPOINT and
relevant records and confirm the goal, constraints, STOP, budget and next action.
Recheck that the old owner has not changed; update only owner and necessary
revision/time fields while preserving the rest of CHECKPOINT. Do not change other
HQs' flags, memory, or native Goal history. Redirect only existing authorized
continuation settings, preserving their state; never create duplicates. Keep the
prior owner until successor acceptance is confirmed.

Use weighted stages to bound continuity when the project has enabled this policy. The default rotation limit is three weighted stages: ordinary stage = 1, stage with a return, a measured log of at least 8,000 characters, or a dispute = 2, and more than two returns = 3. Stage IDs are stable and idempotent. A project may lower the limit to two after confirmed premature compaction; do not raise it above three without evidence.

Rotation may be requested at the next safe boundary by the weighted limit, first confirmed role violation, explicit manual refresh, or supplied context-use telemetry of at least 65%. Never infer context use from transcript length. A trigger does not interrupt an accepted active run or worker. Wait for known idle status; unknown activity or conflicting counters requires inspection. Preserve STOP, quota gate, protocol budgets, pending work, and owner-scoped counters through handoff. Reset counters only after the successor confirms acceptance.

Make a safe handoff as one controlled ownership change. The successor first reads project instructions, OUTLINE, CHECKPOINT, and relevant records, then confirms the goal, constraints, STOP, budget, and next action without writing memory or starting work. Recheck that the old owner has not changed; update only owner and necessary revision/time fields while preserving the rest of the checkpoint. Redirect only existing authorized wakeups, preserving their settings, and do not create duplicates. Have the successor confirm acceptance before archiving the prior owner. If any step fails, inspect actual state and avoid duplicate owners or work.

For task or HQ thread titles use `<task name> HQ · YYMMDD-HHMM`, with the actual creation time in the configured timezone. Keep the task name from the project goal. On confirmed handoff, archive the previous thread while retaining its original task name and creation timestamp. If creation metadata is unavailable, do not invent a timestamp. A naming convention alone does not authorize creating threads or automations.

Quota exhaustion is not an owner-rotation trigger. At the five-hour 90% boundary, minimally checkpoint and end the current HQ turn as specified in [lifecycle](lifecycle.md); defer any otherwise pending rotation until a later authorized invocation passes admission. Do not launch a successor to bypass account quota.
