# Phase 10 Handoff — Final Validation and Release

## Status

**IN PROGRESS — benchmark freeze and first final held-out evaluation accepted; publication/release work remains.**

Phase 10 started from the fully closed Phase 9 `main` head `63eecc9f2561641204d557d3b0aa3ab95c172fa6` on branch `phase-10-final-validation-release`.

## Phase 10 objective

Complete OpsSentinel as a polished engineering and research artifact without introducing major new architecture unless required to repair defects found by final validation.

The exit gate remains cumulative: current-phase validation, all prior regressions, clean-state Docker/Compose, representative end-to-end workflows, persistence/restart checks, security and privacy boundaries, documentation, and CI-equivalent verification must all pass together.

## Checkpoint 10.1 — OpsSentinel Benchmark v1.0 freeze — ACCEPTED

The existing BenchmarkLab release is frozen rather than redesigned:

- benchmark name: `OpsSentinel BenchmarkLab`;
- benchmark version: `1.0.0`;
- scenarios: 50;
- difficulties: easy 10, medium 12, hard 12, adversarial 8, compound 8;
- splits: dev 30, validation 10, hidden test 10.

`benchmarklab/release/opssentinel-benchmark-v1.0.json` pins exact Git blob identities for the scenario/catalog/ground-truth/split definition files and the EvaluationLab files defining RCA, evidence, efficiency, calibration, safety, counterfactual, and report metrics.

`benchmarklab.release.verify_release_freeze()` recomputes those identities from local bytes, revalidates semantic benchmark distributions, and fails closed if the protected research contract moves.

The freeze intentionally does **not** pin execution/runtime files that may require legitimate software-defect repair during final validation.

Accepted freeze workflow on the first clean checkpoint: `34259357625` at `97c927b70c830cf42b6dde22835a1633ff357bf4`. The freeze remained green at the held-out execution head.

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

The uploaded workflow artifact remains the authoritative raw output.

## Research-integrity rule after final evaluation

The frozen benchmark, hidden-test composition, ground truth, metric definitions, and first successful hidden-test result must not be edited or replaced in response to observed performance.

Software defects outside that protected research contract may still be repaired, followed by cumulative reruns. New research hypotheses belong on development/validation data or a future benchmark version.

Negative, null, and surprising findings remain valid outcomes and must be reported as measured.

## Remaining Phase 10 work

1. validate this published result/failure-analysis checkpoint on exact head;
2. assess optional external validation and proceed only if a compatible public SRE benchmark can be used without distorting either task;
3. write the final technical paper/results narrative from recorded artifacts;
4. restructure the README around the research question, system, reproducibility, and measured positive/null/negative findings;
5. add reproducible demo/benchmark/release commands and final release QA;
6. synchronize documentation and portfolio-facing evidence;
7. run the complete Phase 1–10 clean-state cumulative gate;
8. open/review/merge the Phase 10 PR only after exact-head acceptance;
9. revalidate `main` post-merge before declaring the project complete.
