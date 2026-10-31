# Historical record: prior native Goal continuation guidance

> **Historical only; superseded for active CD5 work.** This file preserves prior
> instructions and evidence about native Goals. Current CD5 continuation follows
> [Stop Goal / Continue Goal](file-continuation.md). Do not use the historical
> instructions below to create, resume, update, or clear a native Goal for CD5, or
> to start another driver. Preserve existing native Goal history and usage.

Use the application's persisted thread Goal for ordinary continuous HQ work.
This is separate from OUTLINE, CHECKPOINT.goal_status, a CU goal or a prompt that
says “continue”. Those records do not create native Goal state.

## Authorization and first admission

For an explicitly user-authorized native Goal (including the user's standing
instruction to create a Goal whenever starting their HQ), the **current owner**:

1. Reads instructions, OUTLINE/CHECKPOINT, actual owner/STOP, fresh ordinary
   300-minute quota below90, next authorized action and participant activity.
   Check scientific protocol/permission independently; a Goal grants none.
2. Calls `get_goal` in its own chat. If unavailable, records that native support
   is unverified; never reports an active Goal from a checkpoint flag alone.
3. If no native Goal exists, calls `create_goal` with the authorized objective.
   State the verifiable outcome, permitted work, completion criteria and relevant
   constraints. Keep the objective stable and within4000 characters. Do not create
   a Goal for ordinary unrelated tasks or another chat. A message carrying a
   handoff is not itself evidence that the successor already has a native Goal.
4. Read back with `get_goal` and save a compact `CHECKPOINT.native_goal` observation:
   driver=`native`, actual owner ID, status, objective digest, observation time,
   observed budget/usage if present. Keep permission source and any **explicit**
   pause policy separately. A requested token budget is not WU or quota percent;
   never invent it or derive it from the WU forecast.
5. Reuse an identical active Goal. Never rewrite the same objective every turn:
   replacement can reset accounting. A conflicting objective needs reconciliation;
   paused, blocked, usage-limited, budget-limited or completed Goals are not
   silently resumed/replaced. Preserve the original objective and consumption.

The helper `scripts/native_goal.py` produces a read-only admission plan from
fresh observations and explicit authorization. It cannot create goals, supply
human permission, alter memory or prove a native continuation occurred. The owner
executes appropriate actions with native tools and verifies the returned state.

## During work and normal closure

At a normal useful-work boundary, preserve the active native Goal if permitted
work remains. The application may continue after the turn ends when the thread
is idle, no input/work is pending and the Goal remains active and within budget.
Do not add an hourly “continue” schedule or a second driver for the same owner.
Set CHECKPOINT.native_goal.driver=`native` to prevent `planner_control.py` from
dispatching an external wake. Do not activate a previously paused automation.

Before marking native Goal complete, audit the accepted result against actual
files/tests/evidence and the user's criteria. An intermediate CU completion,
quota boundary, exhausted forecast or absence of another action is not project
completion. Preserve uncertainty and outstanding human decisions.

## STOP, waiting and the90% boundary

Native continuation does not establish knowledge of CD5 STOP, all external
participants or the project's90% reserve. Always perform CD5 admission checks.
When STOP, CD5 off, required human input or quota blocks work, save the reason
and native Goal state, then finish the turn. Never leave a repeated “check quota”
model loop running: quota checks are tool calls and can defeat suppression of
empty continuation turns.

Pause through `update_goal(status="paused")` **only on the user's explicit pause
request**, including a directly authorized standing conditional policy for that
Goal. Record its source and conditions; do not infer permission to pause from
the90% rule alone, declare failure complete, fabricate three blocked turns or
write native Goal databases. If pause authority is absent, request the user's
pause and disclose that automatic continuation is not safely suspended. Do not
call a privileged alternate API to bypass the native tool's lifecycle rules.
If the user directly delegates this specific pause-policy decision to CD5, do not
ask them to design the implementation: record that delegation and choose the
safe policy (pause on STOP, CD5 off, quota admission closed or required human
input). Preserve the objective/accounting and verify the resulting native status.
This is a scoped user delegation, not permission inferred from ordinary work.
Resume remains a user/system operation; `CD5 on` does not silently clear native
pause, STOP or a budget limit. Native blocked status follows the actual host tool
contract, including its repeated-blocker requirement.

## Handoff, recovery and actual verification

Native Goal belongs to one chat. For an authorized owner handoff, first establish
the old owner's safe stop and known participant activity, then have the successor
read/create its own explicitly authorized Goal and confirm ownership. Do not leave
two owners automatically continuing, transfer an assumed token budget, archive
an active owner or change ownership merely to get past a quota boundary.

Native Goal is the preferred ordinary continuation mechanism. Automatic recovery
after quota reset, interruption, application restart or machine reboot is **not
promised** by persisted state alone. Observe actual native lifecycle/consumption;
keep ordinary continuation, quota-reset resume and restart resume as separate
verified/unverified facts. Do not install another scheduler to paper over an
unverified case. Test safe cases in a separately authorized technical chat, not
the working research HQ. Do not claim a full integration from fixture tests alone.

## Quota recovery and lifecycle authority

Keep three states distinct: CD5's preventive `paused` at90%, the host's
`usageLimited` after a quota failure, and `blocked` after a repeated impasse.
A quota reset does not establish that any of those states changed. In particular,
`usageLimited` records why work stopped, not whether account usage is currently
allowed. A successful user-triggered turn can coexist with that stopped Goal.
Read fresh account allowance independently from native Goal state.

Do not describe programmatic resume as inherently impossible: the official
App Server exposes status management to clients. That is different from an
agent's available lifecycle authority. A separate user-controlled integration
needs its own supported connection, authorization, safety gates and end-to-end
verification; a raw API call is not an agent workaround for a missing resume tool.
Third-party auto-resume claims are not proof of installed Desktop behavior and
may cover quota failures without covering CD5's earlier90% pause.

Sources: [OpenAI repository explanation of stopped Goal state](https://github.com/openai/codex/issues/54697#issuecomment-6387017491),
[Goal stopping-state implementation](https://github.com/openai/codex/pull/23094),
and [official Goal API](https://learn.chatgpt.com/docs/app-server#manage-a-thread-goal).

## Read-only diagnostic

For a finite model-free diagnostic, `scripts/native_goal_probe.py --cli <trusted-installed-cli> --owner-thread <UUID>` starts one temporary official stdio service and closes it after reading persisted Goal metadata, current quota and thread metadata. It sends no Goal writes, thread loads or model input. This is an additional temporary service process, not another Desktop window. Its thread runtime status belongs to that service: a Desktop-owned active chat can appear `notLoaded` there. It always reports `wake_supported=false`, unknown workers and unverified live Desktop activity. Never use that result as evidence of idle, authorization to resume, or a production wake adapter. Unavailable Goal/quota is distinct from observed absence; read failure never licenses a retrying model loop.

## Session-start connectivity is not Goal recovery

A local `SessionStart` command hook can receive the actual session ID and the
Desktop-provided tools environment. In a Windows Desktop test, a finite hook
successfully read its own authorized technical chat through the first-party
bundled tools client on `resume`. This establishes connectivity during that
session event only. It does not establish automatic Goal activation, quota-reset
recovery, live participant-idle detection, or recovery after a full application
or computer restart. `CODEX_THREAD_ID` was absent in that hook environment; do not
invent it or copy an agent identity to make another operation work.

Hooks are discovered next to active configuration layers. A projectless test
chat may not be among the project roots scanned by Desktop Settings. A user-level
definition can be listed there, but its script must independently reject every
session except the authorized test target. Disable duplicate definitions before
testing. Review/trust of the exact hook definition remains a human platform step;
installation or an enabled toggle alone is not proof of execution.

Keep a diagnostic read-only, finite, and free of model input and Goal writes.
Reserve a durable one-shot receipt before connecting, preserve interrupted
attempts as unknown, and never silently upgrade a trusted diagnostic into a
resumer. A successful callback is evidence, not authorization to bypass the
native Goal lifecycle contract. See official [Hooks](https://learn.chatgpt.com/docs/hooks).

## Verified ordinary useful continuation

The acceptance condition for ordinary continuity is: after an intermediate turn
ends, without another user message, the mechanism starts the next turn and that
turn performs the next useful authorized step. Keeping Goal active, rather than
pausing/blocking it at every intermediate result, is necessary for this path.

A controlled Windows trial on30Oct2026 verified this with actual work: the first
turn recorded the current commit and a plan for15 synthetic native-Goal regression
tests, then ended with Goal active. The application's natural next Goal turn ran
all15 tests successfully on the unchanged commit and saved the real unittest
result. External history and native Goal context verified that no second message
was sent to start that turn. The test Goal then completed normally.

This is proof of ordinary continuation at an active Goal's idle boundary. It is
not automatic resumption of a deliberate pause, user STOP, closed quota, or a
crashed application. Preserve those as separate scenarios. A missing pre-model
callback remains a separate limitation, not a reason to block independent useful
native work under the current admission rules.

## Sources

An actual Windows trial found that automatic native Goal continuation skipped
UserPromptSubmit, while real UI user input triggered the same trusted recorder.
Do not claim that hook enforces a pre-model native admission gate on the observed
installation. See [the controlled result and limits](continuation-admission.md#observed-native-prompt-hook-limitation).

For the separate, opt-in one-shot Stop experiment and its evidence limits, see
[Stop hook trial](stop-hook-trial.md). Its controlled test flags are not a
production source of live worker/STOP state. It never replaces this HQ's native
Goal driver automatically.

Official [Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)
describes thread-scoped persisted goals, idle continuation and stopping conditions.
The [App Server protocol](https://learn.chatgpt.com/docs/app-server#manage-a-thread-goal)
describes native goal read/set/clear, objective replacement and retained usage.
Host tools and actual installed behavior take precedence over assumptions about
version numbers or availability. API support is not proof of a successful wake.
