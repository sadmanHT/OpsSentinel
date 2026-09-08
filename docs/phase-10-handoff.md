# Phase 10 Handoff — Final Validation and Release

## Status

**IN PROGRESS — checkpoint 10.1 benchmark freeze implemented; exact-head validation pending.**

Phase 10 starts from the fully closed Phase 9 `main` head
`63eecc9f2561641204d557d3b0aa3ab95c172fa6` on branch
`phase-10-final-validation-release`.

No final hidden-test result has been examined as part of Phase 10 before this freeze.

## Phase 10 objective

Complete OpsSentinel as a polished engineering and research artifact without introducing major
new architecture unless required to repair defects found by final validation.

The exit gate remains cumulative: current-phase validation, all prior regressions, clean-state
Docker/Compose, representative end-to-end workflows, persistence/restart checks, security and
privacy boundaries, documentation, and CI-equivalent verification must all pass together.

## Checkpoint 10.1 — OpsSentinel Benchmark v1.0 freeze

The existing BenchmarkLab release is frozen rather than redesigned:

- benchmark name: `OpsSentinel BenchmarkLab`;
- benchmark version: `1.0.0`;
- scenarios: 50;
- difficulties: easy 10, medium 12, hard 12, adversarial 8, compound 8;
- splits: dev 30, validation 10, hidden test 10.

`benchmarklab/release/opssentinel-benchmark-v1.0.json` pins the exact Git blob identity of the
scenario/catalog/ground-truth/split definition files and the EvaluationLab files that define RCA,
evidence, efficiency, calibration, safety, counterfactual, and report metrics.

`benchmarklab.release.verify_release_freeze()` recomputes those blob identities from local bytes,
revalidates the semantic benchmark distributions, and fails closed if the frozen contract moves.

The freeze intentionally does **not** pin execution/runtime files that may require legitimate defect
repair during final validation. Scenario definitions, hidden ground truth, split definitions, and
metric definitions are the protected research contract.

## Research-integrity rule after freeze

Once final held-out evaluation begins, the frozen benchmark, hidden-test composition, ground truth,
and metric definitions must not be edited in response to observed results. Software defects outside
that frozen research contract may still be repaired, followed by cumulative reruns.

Negative, null, and surprising findings remain valid research outcomes and must be reported as
measured.

## Remaining Phase 10 work

1. pass checkpoint 10.1 exact-head CI;
2. run final held-out evaluation against the untouched hidden-test split;
3. produce failure analysis and genuine "what surprised me" findings;
4. perform optional external validation only if a compatible public SRE benchmark can be used
   honestly without distorting either benchmark;
5. write the final technical paper and results artifacts;
6. restructure the README around the research question and measured findings;
7. add reproducible demo/benchmark commands and release QA;
8. run the complete Phase 1–10 clean-state cumulative gate;
9. merge only after exact-head acceptance, then revalidate `main` post-merge.
