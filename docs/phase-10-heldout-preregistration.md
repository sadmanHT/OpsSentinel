# Phase 10 Final Held-Out Evaluation Preregistration

## Status

This protocol is registered **after** the OpsSentinel Benchmark v1.0 freeze passed and **before**
any Phase 10 final hidden-test result is executed or inspected.

Frozen benchmark/evaluator head before this protocol: `97c927b70c830cf42b6dde22835a1633ff357bf4`.

## Evaluation population

Run every scenario whose frozen split is `hidden_test`. The frozen catalog contains exactly ten such
scenarios. Selection is by split, not by scenario outcome, title, fault type, or expected answer.

The final system configuration is the repository's shipped clean-Compose default local provider and
agent configuration. Scenario-specific investigation budgets remain exactly as frozen in Benchmark
v1.0. No hidden-test-specific prompt, tool-order, planning, retrieval, verification, or stopping
strategy is introduced.

## Execution protocol

For each hidden scenario:

1. restore ChaosLab;
2. inject its frozen deterministic faults/stimuli through BenchmarkRunner;
3. send only `scenario.agent_payload()` plus its frozen budget to the agent API;
4. save the completed runtime trajectory;
5. restore ChaosLab in `finally`;
6. adapt the saved trajectory to EvaluationLab only after agent execution;
7. score with the frozen EvaluationLab definitions;
8. fetch the persisted Phase 9 cost/latency summary for the same `agent_run_id`;
9. cross-check tool counts and run identity;
10. retain a sanitized trajectory that excludes evaluator-only expected root-cause labels.

Research outcomes never act as pass/fail accuracy thresholds. CI may fail only for software,
integrity, isolation, restoration, persistence, malformed output, or execution defects.

## Predeclared final metrics

### Diagnostic quality

- `overall_rca_accuracy`: mean frozen primary-root-cause accuracy across all ten runs.
- `exact_match_rate`: mean frozen exact multi-root-cause match.
- `difficulty_primary_accuracy`: the same primary accuracy stratified by frozen difficulty. A tier
  absent from the hidden split is reported as `null`, not zero.
- `compound_primary_accuracy`: primary accuracy over frozen compound-tier hidden scenarios.
- `compound_secondary_recall`: mean frozen secondary-cause recall over those compound scenarios.

### Reasoning quality

- evidence precision, evidence recall, and critical-evidence recall from frozen EvaluationLab.
- `unsupported_claim_rate`: fraction of runs whose frozen failure taxonomy contains
  `UNSUPPORTED_ASSERTION`. This intentionally inherits the frozen taxonomy semantics rather than
  adding a post-results grader.
- useful evidence per tool call, duplicate calls, irrelevant calls, misleading calls, and failed
  calls from frozen EvaluationLab.

### Calibration

- confidence, Brier score, ECE, and reliability bins exactly as produced by frozen EvaluationLab.
  Frozen EvaluationLab calibrates against exact-match correctness; this is retained without
  post-results reinterpretation.

### Operational

- total and mean tool calls;
- total and mean tokens;
- total and mean provider-estimated cost, preserving legitimate zero values;
- p50 and p95 `time_to_diagnosis_ms` using the nearest-rank percentile over non-null persisted
  measurements. If no value is measured, report `null`.

### Reliability and safety

- unsafe action attempts and the other frozen safety counters;
- `tool_failure_recovery_rate`: among runs containing at least one frozen failed tool-call
  assessment, the fraction whose agent run still reaches status `completed`; if no run contains a
  failed tool call, report `null` with affected-run count zero.
- budget-exhaustion and run-status counts are reported descriptively.

### Counterfactual consistency

Counterfactual observations are grouped only by their frozen counterfactual family. A family is
scored only when at least two hidden variants from that same family are present. Overall consistency
is pair-count weighted across scored families. If the hidden split contains no scorable family,
report counterfactual consistency as unavailable/null rather than borrowing validation data.

## Failure analysis artifacts

The workflow retains per-run evaluation results and sanitized runtime trajectories. It does not
publish evaluator-only expected labels in the trajectory artifact. Failed diagnoses and all frozen
failure categories remain visible for later manual Phase 10 failure analysis; no failure category is
removed because it is inconvenient or surprising.

## Percentile and missing-value policy

Latency uses nearest-rank percentiles. Missing measurements stay `null`. Legitimate measured zeros
for local-provider tokens or monetary cost stay zero. No imputation is allowed.

## Change control after first execution

After the first final hidden-test execution begins, do not change this metric protocol, the frozen
benchmark, hidden-test membership, ground truth, or frozen EvaluationLab definitions merely because
of observed results. If a genuine software bug is found, repair the software outside the protected
research contract, document the defect, and rerun the complete relevant evaluation chain.
