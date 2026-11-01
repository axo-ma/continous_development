# Forecast, limit and actual WU

These are separate values for one whole CU, including HQ, executors, helpers and review:

- **Forecast**: an expected WU range with low/medium/high confidence. It guides work; it is not a spending cap or a quality target. Include a rough assessment in normal planning, without a separate estimator agent or long explanation. HQ supplies a numeric whole-team range before new work; it is internal planning, never a request for user approval. For unfamiliar work, give a wider justified range; an unknown reason never replaces the number.
- **Limit**: an optional maximum allocation independent of the forecast. Identify its authority: an internal allocation is chosen/revised by HQ; an actual user-imposed cap cannot be increased by HQ. Do not silently turn the forecast's upper bound into a limit. It cannot override user permissions, project STOP, quotas or scientific budgets.
- **Actual**: the factual WU derived by the existing usage collector and dated base-cost estimator. It can be incomplete until journals settle. Verified observed counters in an open turn are displayed as an explicitly partial amount at the snapshot time; missing duration does not erase valid token measurements. Do not compare unknown/partial amounts as though they were a complete actual.

## Minimal owner workflow

Reuse the normal begin mark with a rough prospective forecast (synthetic example):

```
python <skill>/scripts/control_units.py --root <project> begin --cu <id> --title "Existing task" --caller-thread <owner> --forecast-low 3 --forecast-high 6 --confidence medium
```

Normal `begin` and new non-historical `record` opens require both numeric ends of the whole-team range. Unknown-reason-only opens fail before writing. Historical imports and event replay remain compatible; never backfill an absent original forecast. Before continuing an older open CU, save a numeric prospective revision for remaining work, clearly distinct from the missing original. No WU limit is required.

Pass CU ID, forecast range/confidence and any separately authorized limit in the existing executor brief. The executor uses the forecast as orientation, avoids unnecessary repeats, and reports material scope/cost changes with the cause and remaining work. Do not lower quality merely to fit the forecast. If the limit appears insufficient, return to HQ before starting further work expected to exceed it; HQ chooses the next step or revises its internal allocation and continues within the assigned plan. Only an actual user cap requires respecting the user boundary; an executor returning to HQ is not returning to the human. The end of one allocation/attempt never by itself closes the whole plan. Do not send repeated bookkeeping messages for each tool call. A whole-team CU allocation must not be copied as a full personal budget to each agent.

An explicit revision keeps the original values and adds a short reason:

```
python <skill>/scripts/control_units.py --root <project> budget --cu <id> --caller-thread <owner> --event-id <stable-revision-id> --forecast-low 5 --forecast-high 9 --limit-wu 10 --reason "Existing scope change"
```

Omitted values are preserved. `--clear-limit` removes the optional limit without erasing history. A forecast for active non-historical work cannot be cleared; revise its numeric range. Repeating an event ID is idempotent; changed content requires a new ID. `finish` still reuses the existing short result and does not require a separate budget report.

The program records the initial forecast only if supplied at CU open. Later estimates remain revisions, not fabricated predictions from before work. Closed CU budgets cannot be rewritten after observing results. When comparing for calibration, keep the original forecast as the baseline even when the current planning range changes; show the saved revision history in details. Do not backfill historical forecasts.

## Report and interpretation

The main WU cell shows **План / Факт**. Limits are not shown in the report, including CU details; existing limit records remain in canonical history. Missing forecasts show the recorded reason, or explicitly state that no prospective forecast was recorded. Team details retain participant actuals; forecast/limit are not duplicated as per-participant budgets. Task/result details show confidence, original forecast and dated revisions. The footer is explicitly factual usage for the whole selection across pages, not a sum of unrelated forecasts or limits.

Only complete actuals with the same dated API base-cost basis are compared. A still-open CU can already exceed the original forecast, but cannot be declared to have finished below/within it. A completed CU is classified relative to its original range. Limit comparisons stay in the underlying data; the implementation does not kill agents, cancel work, resume a project or install schedules. Journal collection is deferred to reads and cannot promise a real-time hard spending guard. Changes of tariff date or accounting basis leave comparison unknown instead of creating a misleading verdict. WU is not subscription capacity.

This version records forecasts and comparisons; it does not train an estimator, invent historical estimates or automatically generate forecasts from insufficient examples.
