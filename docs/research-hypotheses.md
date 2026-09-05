# Research Hypotheses

These hypotheses are registered before the research phases. They are **not expected results**. Negative, null, or surprising results must be reported as measured.

## H1 — Planning heterogeneity

Explicit planning may help difficult and compound incidents while adding unnecessary latency, tokens, or tool calls to easy incidents.

## H2 — Over-investigation

Beyond some investigation depth, additional tool calls may provide diminishing information and may reduce root-cause accuracy by increasing exposure to distractors or co-occurring symptoms.

## H3 — Temporal reasoning

Requiring an agent to validate the temporal relationship between a candidate cause and the effect onset may reduce correlation-based anchoring, especially around misleading recent deployments.

## H4 — Confidence calibration

Passive evidence collection may increase expressed confidence faster than correctness, while deterministic verification tools may improve calibration.

## H5 — Compound failures

Agents may prematurely converge after identifying one legitimate cause and fail to identify a simultaneous secondary or pre-existing failure.

## Research integrity

Do not alter benchmark labels, tests, scoring rules, or experimental code merely to make a hypothesis appear true. Software defects must be fixed until validation passes; research outcomes must remain data-driven.
