# Phase 10 Held-Out Results and Failure Analysis

## Provenance

This document reports the first successful execution of the preregistered final held-out protocol against the frozen OpsSentinel Benchmark v1.0 hidden-test split.

- benchmark: `OpsSentinel Benchmark v1.0` (`1.0.0`)
- hidden split: 10 untouched scenarios
- execution commit: `e9295448e7b96f5527863a8f00416fe0fa05d85e`
- workflow run: `34260392909`
- artifact: `phase10-heldout-evaluation`
- artifact digest: `sha256:9e5f7aca335941b0126054434615d1d5989fc53f4ea114e082e08b0e6a96780a`
- published safe summary: `results/phase10/heldout-summary.json`

The benchmark and evaluator contract was frozen before this execution. No hidden scenario, hidden ground truth, split assignment, or scoring definition was changed after final evaluation began. Accuracy was not a CI pass threshold: the workflow passed because the software, clean-stack execution, artifact production, restoration, privacy boundary, and teardown succeeded.

## Headline result

The final hidden cohort produced **0.80 primary RCA accuracy but only 0.20 exact diagnosis match**.

That gap is the central Phase 10 result. OpsSentinel usually found the acute primary fault, but it did not reliably recover the complete causal picture when two genuine failures coexisted.

## Quality metrics

| Metric | Result |
| --- | ---: |
| Hidden runs | 10 |
| Primary RCA accuracy | 0.80 |
| Exact-match rate | 0.20 |
| Adversarial primary accuracy | 1.00 |
| Compound primary accuracy | 0.75 |
| Compound secondary-cause recall | 0.00 |
| Evidence precision | 0.7833 |
| Evidence recall | 0.475 |
| Critical-evidence recall | 0.475 |
| Unsupported-claim rate | 0.00 |

The hidden split contains two adversarial scenarios and eight compound scenarios. Easy, medium, and hard difficulty metrics are therefore `null` for this final hidden cohort rather than imputed from development or validation data.

## Calibration

- Brier score: **0.56501**
- expected calibration error: **0.573**
- six incorrect/incomplete diagnoses were classified as `OVERCONFIDENCE`

Six compound runs found a correct primary cause with confidence between **0.96 and 0.99**, but still emitted no expected secondary cause. High confidence therefore did not imply completeness.

Two other compound runs returned an `inconclusive` diagnosis at confidence `0.0`. These were not execution failures: the outer agent runs still reached `completed`, and the final workflow restored the environment successfully.

## Efficiency and operational measurements

| Metric | Result |
| --- | ---: |
| Total tool calls | 27 |
| Mean tool calls/run | 2.7 |
| Useful evidence/tool call | 0.75 |
| Irrelevant tool calls | 7 |
| Duplicate tool calls | 0 |
| Misleading tool calls | 0 |
| Failed tool calls | 0 |
| Diagnosis latency p50 | 153.839 ms |
| Diagnosis latency p95 | 388.212 ms |
| Completed agent runs | 10/10 |
| Budget-exhausted runs | 0 |

The compound scenarios allow substantially more investigation than the 2–4 calls actually used in the observed trajectories. The failures are therefore not explained by budget exhaustion. The evidence is more consistent with early convergence and incomplete evidence collection.

That observation must not be simplified into “more tool calls would fix the problem.” Phase 8 already found that forced additional verification/investigation could add cost or even reduce RCA quality. The defensible conclusion is narrower: the current stopping/evidence-selection behavior does not reliably distinguish “primary cause found” from “causal picture complete.”

## Safety, tokens, and cost

- unsafe action attempts: **0**
- blocked destructive requests: **0**
- unnecessary approval requests: **0**
- incorrectly classified risk: **0**
- provider-reported total tokens: **0**
- provider-estimated total cost: **0.0**

The zero token/cost values are genuine measurements from the deterministic local provider used by this evaluation. They are not estimates of hosted-model economics and must not be presented as such.

No hidden run contained a failed tool call, so tool-failure recovery rate is `null` rather than `0.0` or `1.0`.

## Counterfactual metric availability

Counterfactual consistency is **unavailable** for this final hidden cohort because the frozen hidden split contains no scorable counterfactual family. The result remains `null`; validation-set counterfactual observations are not mixed into the hidden-test result.

## Failure taxonomy

EvaluationLab produced the following aggregate failure classifications:

| Failure category | Count |
| --- | ---: |
| `COMPOUND_CAUSE_OMISSION` | 8 |
| `MISSED_EVIDENCE` | 8 |
| `OVERCONFIDENCE` | 6 |
| `TOOL_MISUSE` | 5 |

### Dominant mechanism: compound-cause omission

All eight compound scenarios omitted the expected secondary cause. Six still identified the primary cause correctly, explaining why primary RCA accuracy remains high while exact-match accuracy collapses.

The benchmark's compound construction intentionally contains two real failures: an older genuine secondary degradation and a later primary fault responsible for the acute onset. The final trajectories frequently converged on the later acute fault without collecting enough evidence to represent the older coexisting fault.

### Missed evidence

Critical-evidence recall was only **0.475** overall. Compound runs commonly retained only one-quarter or one-half of the benchmark's critical evidence set. This aligns with the compound omissions and supports an evidence-completeness interpretation rather than a tool-crash interpretation.

### Tool misuse

Five runs were classified with `TOOL_MISUSE`, while there were zero failed, duplicate, or misleading calls. In the frozen evaluator, this category reflects irrelevant investigation calls. It therefore describes efficiency/selection quality, not infrastructure instability.

## What surprised us

The most important surprising result is that **80% primary RCA accuracy coexists with only 20% exact diagnosis accuracy**. A primary-only metric would make the final system look materially stronger than a complete-causal-diagnosis metric.

A second surprise is that the two adversarial hidden cases were solved exactly while the compound cohort was the dominant weakness. The final challenge was not primarily resisting obvious false leads; it was maintaining investigation breadth after a plausible acute cause had already been found.

A third result is the calibration failure: high-confidence primary correctness did not translate to high-confidence complete correctness. The current confidence signal appears better aligned with “I found a plausible primary cause” than with “I have explained the full incident.”

## Interpretation limits

These results apply to the frozen 10-scenario hidden split and the exact runtime/configuration recorded by the workflow. The hidden sample is deliberately small and structurally weighted toward adversarial and compound cases, so it should not be described as a universal production incident distribution.

No external benchmark result is included here. Any external validation must be reported separately and must not be transformed into an OpsSentinel Benchmark score if the task, labels, tools, or observability assumptions are incompatible.

## Research-integrity rule

These results are now immutable research evidence. Future engineering work may repair software defects or explore new hypotheses on development/validation scenarios, but it must not edit the frozen v1.0 hidden scenarios, ground truth, split definitions, metric definitions, or this recorded first successful hidden result in response to performance.
