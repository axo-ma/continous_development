# CD5 memory

The default memory directory is `coordination/cd5`, configurable by project-local `.cd5/config.json`. Use exactly these five canonical current records unless an established project schema explicitly defines another layout:

| File | Purpose |
| --- | --- |
| `OUTLINE.md` | Goal, milestones, broad plan, risks, success criteria, and boundaries |
| `CHECKPOINT.json` | Current owner, STOP state, active task, next action, budgets, and authorized automation state |
| `EVIDENCE.jsonl` | Stable-ID catalogue of sources, artifacts, and execution witnesses |
| `KNOWLEDGE.jsonl` | Observations, conclusions, unknowns, hypotheses, decisions, and accepted task results with evidence links |
| `ATTENTION.jsonl` | Current items that need a human decision or attention |

The configured `owner_role` is the sole writer of OUTLINE, CHECKPOINT, KNOWLEDGE, and ATTENTION. Other roles may append permitted EVIDENCE records through the project's supported mechanism. Treat tool role labels as cooperative workflow metadata, not authentication.

Keep EVIDENCE and KNOWLEDGE distinct: evidence records what was observed or which artifact exists; knowledge records what is inferred and under what limits. An event or artifact alone does not prove a claim or advance a milestone. Absence of evidence is not a negative finding. Preserve the distinctions among unknown, untested, and negative.

Control Unit state, participant links and measured intervals are artifact events in EVIDENCE. The Progress Report is a derived view, not a sixth canonical file. Use [control units](control-units.md) for granularity and bounded hot-event retention. Verified cold archives preserve IDs for explicit lookup; do not feed whole archives into model context or confuse a reporting completion with an accepted scientific conclusion.

Record accepted work in KNOWLEDGE with stable task and milestone IDs, goal, result, meaning, and references to existing evidence. Accepting a report as a record does not mean its scientific result is positive or that a milestone is complete. Update the matching milestone and its latest change in OUTLINE only when the task result is accepted. Do not reconstruct historical progress from prose or experiment events; if structured records are absent, say so.

Human gold requires actual human acceptance only when labelling a human reference; agent evaluation remains usable as agent evaluation and does not block work. A view/click is not a human verdict. Preserve old protocol versions, assessments and spent attempts. HQ itself accepts and versions changes to questions, criteria, cases and internal budgets within the assigned plan; no new human approval is implied. Only actual user constraints and mandatory system permissions require human action. See [HQ authority](hq-authority.md).

Follow [outline](outline.md) for the project plan structure, risk ordering, milestone completion and the boundary with CHECKPOINT. Keep exact next actions and operational rules out of OUTLINE.
