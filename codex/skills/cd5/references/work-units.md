# Work Units (WU)

For forecasts, separately authorized limits and original-versus-actual comparisons, read [WU budgets](wu-budgets.md). They are CU planning metadata; this estimator continues to compute actual base usage from source tokens and never treats missing data as zero.

WU is the normalized API base-cost measure used by the Progress Report. **CU** identifies the work being controlled; **WU** expresses its estimated resource cost. WU is not a subscription token, a quota percentage, or an available balance.

The agreed denomination is **1 WU = $0.10**, anchored to the API Standard price of one million GPT-6 Luna uncached input tokens on **2026-10-21**. Prices are a dated configuration in `scripts/work_units_rates.json`, with their source URL. Rendering performs no network requests or LLM calls. Do not silently refresh prices or change the denomination when opening old reports. An explicit alternate dated snapshot can be supplied with `control_unit_report.py --rates <path>`.

| Model | Uncached input | Cached input | Output, including reasoning |
| --- | ---: | ---: | ---: |
| GPT-6 Luna | 1 WU | 0.1 WU | 5 WU |
| GPT-6.1 Terra | 10 WU | 0.5 WU | 50 WU |
| GPT-6.1 Sol | 20 WU | 1 WU | 100 WU |
| GPT-6 Sol, preserved legacy snapshot | 20 WU | 2 WU | 100 WU |
| GPT-6 Astra | 100 WU | 10 WU | 500 WU |

Rates are per million tokens. The legacy Sol 6 cached coefficient must not be applied to Sol 6.1. Model matching is explicit; an unknown model is not silently mapped to another tariff.

The additive tariff verified on 2026-10-26 adds Terra 6.1 at API Standard prices of $1 uncached input, $0.05 cached input and $5 output per million tokens. Its verification date is recorded in model_additions; the original rate_date remains the existing forecast comparison basis. Existing model coefficients and the $0.10 WU denomination are unchanged. Terra costs 10 times Luna for uncached input/output and 5 times for cached input at equal token counts; it costs half of Sol 6.1 in all three categories. This is an API price comparison, not a subscription quota multiplier or permission to select a model. The pre-addition snapshot is preserved as work_units_rates.2026-10-21.json.

Cost is computed separately for each participant from the three observed token counts, then summed only when accounting scope and coverage permit it. Effort remains visible metadata and has no separate price multiplier. Reasoning is already part of output and is never added again. Decimal arithmetic retains full precision; the UI normally rounds to two decimal places. Selection totals use unrounded participant costs, not the sum of displayed rounded values. Reopening a report recalculates derived values from raw tokens rather than trusting previously embedded WU.

An actor with missing counts, unknown model, or unsplit mixed-model observations has no complete WU value. Unknown values display as a dash, not zero. A measured zero is allowed. Team/selection totals are not presented as complete if any required participant or scope is unknown. Safe known subtotals are explicitly labelled partial and include only counters whose independent scope is established; they must not be mistaken for a complete result or a subscription balance. Duplicate participant/CU identities within a selection are rejected rather than silently counted twice.

The visible label is **«Базовая оценка»**: API Standard, short context, text token prices. Fast/Ultrafast processing, long-context adjustments, cache writes, paid tools and regional premiums are excluded. If such facts are known, preserve them as provenance; do not describe this base estimate as the actual charge. Local inference remains a separate resource domain. Never infer subscription capacity, reset budgets, or remaining WU from this estimate. In particular, speculative values such as 40 WU per five hours or 800–1000 WU per four weeks are not limits and must not become budget bars.

The main table shows one WU column instead of three token columns. The expanded team retains exact cached input, uncached input and output alongside model/effort, measured time and WU per participant. The selected-view total covers all pages; switching views must select that view's own total, never add costs from overlapping views. Detailed saved text and source references remain available without generating new narratives.

Verified regression: the historical HQ source-search/STOP row has cached input 2,876,928, uncached input 58,861 and output 7,602, all Sol 6.1. HQ cost is **3.107828 WU**, reviewer **1.706520 WU**, total **4.814348 WU**, displayed **4.81 WU**. This is an accounting example, not new scientific acceptance or a prospective CU boundary.

Source: [OpenAI API pricing](https://developers.openai.com/api/docs/pricing); the exact dated coefficients are preserved in the configuration, including the explicitly retained legacy Sol 6 snapshot.
