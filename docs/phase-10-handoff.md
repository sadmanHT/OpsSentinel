# Phase 10 Handoff — Final Validation and Release

## Status

**FULLY CLOSED — final benchmark freeze, preregistered held-out evaluation, publication, cumulative release gate, guarded merge, and post-merge validation all accepted.**

Phase 10 started from the fully closed Phase 9 `main` head `63eecc9f2561641204d557d3b0aa3ab95c172fa6` on branch `phase-10-final-validation-release`.

## Phase 10 objective

Complete OpsSentinel as a polished engineering and research artifact without introducing major new architecture unless required to repair defects found by final validation.

The exit gate was cumulative: current-phase validation, all prior regressions, clean-state Docker/Compose, representative end-to-end workflows, persistence/restart checks, security and privacy boundaries, documentation, and CI-equivalent verification had to pass together.

## Checkpoint 10.1 — OpsSentinel Benchmark v1.0 freeze — ACCEPTED

The existing BenchmarkLab release was frozen rather than redesigned:

- benchmark name: `OpsSentinel BenchmarkLab`;
- benchmark version: `1.0.0`;
- scenarios: 50;
- difficulties: easy 10, medium 12, hard 12, adversarial 8, compound 8;
- splits: dev 30, validation 10, hidden test 10.

`benchmarklab/release/opssentinel-benchmark-v1.0.json` pins exact Git blob identities for the scenario/catalog/ground-truth/split definition files and the EvaluationLab files defining RCA, evidence, efficiency, calibration, safety, counterfactual, and report metrics.

`benchmarklab.release.verify_release_freeze()` recomputes those identities from local bytes, revalidates semantic benchmark distributions, and fails closed if the protected research contract moves.

The freeze intentionally does **not** pin execution/runtime files that may require legitimate software-defect repair during final validation.

Accepted freeze workflow on the first clean checkpoint: `34259357625` at `97c927b70c830cf42b6dde22835a1633ff357bf4`.

## Checkpoint 10.2 — preregistered final hidden-test evaluation — ACCEPTED

The final measurement protocol was committed before a hidden scenario successfully executed. It specifies frozen exact-match calibration correctness, frozen `UNSUPPORTED_ASSERTION` semantics, nearest-rank diagnosis latency percentiles, honest null handling, saved safe trajectories, post-hoc EvaluationLab scoring, and no accuracy threshold for CI.

The first successful hidden-test campaign ran all ten untouched `HIDDEN_TEST` scenarios on a clean stack:

- execution commit: `e9295448e7b96f5527863a8f00416fe0fa05d85e`;
- workflow run: `34260392909`;
- artifact: `phase10-heldout-evaluation`;
- artifact digest: `sha256:9e5f7aca335941b0126054434615d1d5989fc53f4ea114e082e08b0e6a96780a`;
- stack startup/health: passed;
- ten hidden executions: passed as software runs;
- ChaosLab restoration/log checks: passed;
- artifact upload: passed;
- teardown: passed.

Research quality results are intentionally not treated as software-gate failures.

### Measured final hidden results

- primary RCA accuracy: **0.80**;
- exact-match rate: **0.20**;
- adversarial primary accuracy: **1.00**;
- compound primary accuracy: **0.75**;
- compound secondary-cause recall: **0.00**;
- evidence precision: **0.7833**;
- evidence recall / critical recall: **0.475 / 0.475**;
- unsupported-claim rate: **0.00**;
- Brier score: **0.56501**;
- ECE: **0.573**;
- total tool calls: **27**, mean **2.7/run**;
- useful evidence/tool call: **0.75**;
- diagnosis latency: **153.839 ms p50**, **388.212 ms p95**;
- completed outer agent runs: **10/10**;
- budget-exhausted runs: **0**;
- failed tool calls: **0**;
- unsafe action attempts: **0**;
- provider-reported tokens/cost: **0 / 0.0** for the deterministic local provider;
- counterfactual consistency: **unavailable/null** because the hidden cohort has no scorable counterfactual family.

Failure taxonomy:

- `COMPOUND_CAUSE_OMISSION`: 8;
- `MISSED_EVIDENCE`: 8;
- `OVERCONFIDENCE`: 6;
- `TOOL_MISUSE`: 5.

The central finding is that primary-cause success materially overstates complete causal diagnosis on compound incidents. Six compound runs identified the primary cause at 0.96–0.99 confidence but omitted the secondary cause; two compound runs produced an `inconclusive` diagnosis at 0.0 confidence while still completing operationally.

Published research records:

- `results/phase10/heldout-summary.json`;
- `docs/phase-10-heldout-results.md`.

The first successful workflow artifact remains the authoritative raw output. Later held-out runs are reproducibility/regression evidence and do not replace the research measurement.

## Checkpoint 10.3 — publication and external-validation decision — ACCEPTED

The final research report, research-first README, held-out summary, failure analysis, reproducibility commands, and external-validation compatibility decision were published without rewriting null/negative findings.

No external numeric score was manufactured. AgenticOpsEval/RCA100, RootCauseBench, and ITBench-AA were assessed as materially different agent/task surfaces requiring separately preregistered adapters rather than an artificial direct comparison.

## Checkpoint 10.4 — cumulative pre-merge release gate — ACCEPTED

The final Phase 10 PR was gated on one exact head and required all intended cumulative workflows to run rather than treating a path-filter skip as a pass.

Exact accepted PR head:

`46573b40cb35022606414a4a7028762cbe1a6ad0`

All **18/18** intended workflows passed on that exact head:

- CI;
- Phase 6 BenchmarkLab;
- Phase 7 EvaluationLab;
- Phase 8 ResearchLab;
- Phase 8 H3 Temporal;
- Phase 8 Tool Order;
- Phase 8 Passive vs Verification;
- Phase 8 Compound Handling;
- Phase 9 Pareto;
- Phase 9 Latency;
- Phase 9 OpenTelemetry;
- Phase 9 Prometheus Grafana;
- Phase 9 Langfuse;
- Phase 9 Incident Console;
- Phase 9 Experiment Dashboard;
- Phase 9 Representative Frontend;
- Phase 10 Benchmark Freeze;
- Phase 10 Final Held-Out Evaluation.

No failed gate was ignored. The missing Phase 9 release-path coverage discovered during acceptance was repaired before merge so those workflows genuinely executed on the final head.

## Checkpoint 10.5 — guarded merge and post-merge `main` validation — ACCEPTED

PR #12, **Phase 10: final validation, research report, and release**, was merged only after re-confirming the exact green head and using an expected-head SHA guard.

Release merge commit:

`e1e63bd50b481e0a2504cbb5b07971cf59067f3f`

The exact merge commit then passed:

- generic cumulative CI, including clean-state Compose integration and restart/cleanup regression;
- Phase 10 Benchmark Freeze;
- Phase 10 Final Held-Out Evaluation from a clean stack, including restoration/log checks, artifact upload, and teardown.

This completed Phase 10 and the Phase 1–10 release chain.

## Later presentation-only frontend redesign

After Phase 10 closure, the React Incident Console and Experiment Dashboard were visually redesigned in a light data-product theme without changing backend, agent, evaluator, benchmark, API, or research-result semantics.

Frontend merge commit:

`337f2bb8b26ed89509e96e65472bb21d6d725bd3`

Its exact PR head passed the relevant browser/frontend, CI, observability, BenchmarkLab, EvaluationLab, freeze, and held-out regression workflows. The merge commit then again passed post-merge CI, Phase 10 Benchmark Freeze, and Phase 10 Final Held-Out Evaluation.

The redesign is presentation-only and does not change the authoritative first preregistered hidden result above.

## Research-integrity rule after final evaluation

The frozen benchmark, hidden-test composition, ground truth, metric definitions, and first successful hidden-test result must not be edited or replaced in response to observed performance.

Software defects and presentation changes outside that protected research contract may be repaired, followed by cumulative regressions. New research hypotheses belong on development/validation data or a future benchmark version.

Negative, null, and surprising findings remain valid outcomes and must be reported as measured.
