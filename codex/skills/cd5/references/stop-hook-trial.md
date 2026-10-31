> **Historical/diagnostic reference, superseded for active CD5 continuation.**
> Current architecture is [one shared Continuator and CD5 controls](file-continuation.md).
> Native agent Goal is not a CD5 driver. Do not activate legacy wakeups or follow
> old native-only instructions below for current HQs; preserve the historical evidence.

# One-shot Stop trial

`scripts/stop_hook_trial.py` is a deliberately bounded integration trial, not an
installed continuation driver. Installation alone never adds its hook definition.
The owner explicitly authorizes a separate technical chat, with no native Goal,
tools or workers. The working HQ retains native Goal as its sole driver.

Use a frozen script copy, exact target session and separate state/receipt directory
for each authorized attempt. Trust the exact Stop and Interrupt command definitions
through the host UI. Never edit trust hashes or delete a receipt to hide a retry.
The Interrupt definition revokes the trial state. All other sessions are no-ops.

The state requires `authorized=true`, `stop=false`, `waiting_user=false`,
`goal_complete=false`, `workers_idle=true`, `goal_absent=true`, `driver=stop_trial`,
matching target/owner and generation1, and remaining step `CD5_STOP_STEP_TWO`.
These are controlled trial preconditions, not independent live observations of a
general project. Never copy these booleans into a production admission adapter.

The target first answers exactly `CD5_STOP_STEP_ONE`. The hook requires a real
Stop event with turn ID and `stop_hook_active=false`, then reserves a durable
one-shot receipt before reading account usage. It uses the actual hook-provided
Desktop MCP environment and an explicitly selected bundled app-tools server file.
It does not create a second app-server, mutate Goal or send a model prompt itself.
The finite quota read must establish ordinary allowance and a 300-minute Codex
window below90. Missing environment, read failure or changed state denies output.
Only then does it return the platform's `decision=block` with the second-step
instruction. JSON stdout uses ASCII escapes for Windows legacy pipe encodings.

A receipt with `block_once` proves intent, not host acceptance. Verify two native
model response records and exactly the two expected answers in the same session;
inspect host turn completion as well. Disable trial authorization after the result.
Repeated events and interrupted/unconfirmed receipts must not be replayed.

## Observed limits

A Windows Desktop trial on30Oct2026 observed real quota reading through the hook
connection and exactly one additional response in the same chat. A first attempt
failed while emitting non-ASCII stdout; its receipt was preserved and a distinct
trusted attempt verified the fix. Synthetic tests separately exercise closed gates,
duplicates, interruption during quota read, unknown reads and reserved receipts.
These observations do not prove general worker coverage, pending approvals,
production STOP synchronization, continuous multi-stage operation, quota resume,
or Desktop/computer restart recovery.

For production, retain native Goal unless another driver is explicitly chosen.
Do not activate both. Before generalizing the hook, establish an authoritative
source for user control events, all active workers and pending input, bind each
permission to a current owner generation and useful next step, and verify those
sources in the same host. Unknown activity must deny continuation. A static
checkpoint or this trial's controlled booleans do not establish those facts.

Official behavior: [Hooks](https://learn.chatgpt.com/docs/hooks).
