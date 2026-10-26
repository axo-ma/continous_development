---
name: mac
description: Coordinate optional, bounded work with native subagents under one switchable local mode.
---

# Multi-Agent Chat (MAC)

Use MAC when the user invokes a MAC command or a useful separable task makes delegation worthwhile. The primary remains the current chat and owns scope, coordination, integration, and consequential decisions. Avoid delegation when the task is too small to benefit.

Resolve local settings through `python <installed-mac>/scripts/mac_settings.py [auto|off|status]`; `--skill-dir` can explicitly select another installation. The default is the skill directory containing that script, not the current working directory. `MAC auto` and `MAC off` set the one mode; `MAC status` reports it. Read it before every optional launch, including nested helpers. Do not maintain duplicate enabled switches. A disabled mode blocks optional assignments. Missing settings default to auto; invalid settings require inspection, never automatic enabling. Project STOP, authorization and budgets remain controlling.

MAC is independent of CD5. The root primary may launch executor, reviewer, consultant, or helper; a main role may directly launch bounded helpers; helpers never delegate; maximum depth is primary → main role → helper; only the root primary launches reviewers and consultants. Executor may request review or consultation; reviewer may request consultation; the primary launches and receives their conclusions. Each assignment states goal, context, constraints, expected result, verification, permitted write area, shared budget and allowed helper count/concurrency. Helpers return to their caller; do not forward their transcripts to the primary. If platform tools prohibit nesting, report the limitation rather than quietly adding a routing ceremony.

Select models and reasoning effort from current availability and local settings. Report unavailable or unknown model details honestly. The primary checks results and keeps decisions. A self-check is not an independent review, and agent work is not human gold.

When the user restricts models, store their exact IDs in local settings under `model_policy.allowed_models`. Before every assignment, including nested helpers and thread model overrides, run `scripts/mac_settings.py check-model --model <exact-id>` (add `--role <role>` when selecting a configured role). Only a successful result permits that assignment. Pass that exact model to the host; never use an implicit inherited/default model, alias, downgrade or retry with another model after rejection. A missing/invalid policy or forbidden configured role fails closed. Availability must still be checked separately. This is a checked MAC workflow boundary, not a provider-wide lock on unrelated Desktop chats, direct tool calls or another client's API requests. Do not claim a universal application-level prohibition from a Python guard. Historical tariffs and journal model names are evidence, not permission to select them.

The executor owns a complete bounded result; a helper performs a limited step. Delegate when the result can be accepted independently and brief/review cost is justified. Main roles retain evaluation, acceptance and substantive conclusions. Every helper brief forbids further delegation. Before any budget change return to the primary. All helpers consume their caller's allocated budget, not a new budget. Read [accounting](references/accounting.md) when reporting participant usage.
