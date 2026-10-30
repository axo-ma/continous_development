# Worker observations

`hook_event_probe.py` is a target-session-only event recorder. It never sends
model input, mutates a Goal or returns a continuation decision. Trust an exact
frozen definition through the normal host UI before a live trial.

`worker_observations.py` retains every observed worker identity. Both start and
stop observations can discover an identity; neither removes it. A live Windows
Desktop trial observed one SubagentStart for a new helper, but no second start
for its followup. Two SubagentStop events and independent Desktop reads proved
both tasks completed. Therefore balanced start/stop counters are unsafe.

Before admission, obtain a fresh same-host read for **every** retained identity,
including helpers which previously finished. `assess` checks explicit owner and
generation, finite observation times, maximum age (default5 seconds), and an
unambiguous idle status. Active, waiting, notLoaded, systemError, missing, stale,
future, duplicate or mismatched observations deny the known-worker check.
An observed Interrupt remains a stop signal within that event history.

The observation's provenance must be established by its caller; constructing
an object with status=idle is not an actual host read. No polling loop or model
is part of these functions.

## Coverage is separate

An empty or fully idle known list never proves that all workers are known.
`coverage_verified` is always false in this component. Before any production
continuation, establish the baseline inventory, all launch paths, nested workers,
lost events and recovery after a process/app restart. Bind coverage to the owner
generation; changing owner invalidates old status reads. A missing event receipt
is unknown, not proof that no work occurred. The recorder deliberately does not
enroll unrelated sessions automatically.

In the live nested trial both executor and leaf hooks used the original root
session_id. It identifies the observed session group, not necessarily the
immediate caller. The registry includes all such identities; it can also resolve
explicit nested session links when supplied, without relying on receipt order.
The hook's turn_id identifies the child turn. Do not equate that turn_id with the
root's current turn. Independent Desktop reads confirmed both descendants idle
and their tasks completed after the nested trial.
SubagentStop runs at a boundary where another hook can continue the child. It
does not by itself establish terminal completion or current idleness.

Keep the working HQ's native Goal as its only driver. These diagnostic components
do not enable automatic quota resume, restart recovery or a second dispatcher.

Source: [official Hooks documentation](https://learn.chatgpt.com/docs/hooks).
