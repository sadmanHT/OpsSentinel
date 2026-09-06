# Phase 6 Handoff — BenchmarkLab: Difficulty, Adversarial, and Compound Incidents

## Status

**Branch closeout candidate; not yet fully closed.** The complete Phase 1–6 code gate passed on branch head `263133d29983b44d26ef5dff8a0532470330bf58` in CI run **#100**, and the dedicated Phase 6 BenchmarkLab workflow run **#38** passed its static and live gates on the same branch state. Phase 6 still requires a documentation-inclusive rerun, PR #8 merge, and post-merge `main` cumulative revalidation before it may be declared fully complete.

## Implementation summary

Phase 6 turns OpsSentinel from an autonomous incident-response agent demo into a reproducible benchmark laboratory for studying diagnostic reasoning under realistic, noisy, temporal, adversarial, compound, and counterfactual incidents.

Implemented behavior includes:

- a standalone typed `benchmarklab/` package with strict Pydantic contracts for benchmark catalogs, scenarios, difficulty, split, faults, stimuli, timelines, public incident payloads, ground truth, budgets, launch records, and benchmark run artifacts;
- an exact deterministic v1 release catalog of **50 scenarios** distributed as 10 Easy, 12 Medium, 12 Hard, 8 Adversarial, and 8 Compound;
- structural dataset holdouts across development, validation, and hidden-test splits rather than random near-duplicate assignment;
- explicit temporal-causality representation with cause/effect/distractor event ordering;
- a controlled four-variant counterfactual family for deploy/cron/latency consistency analysis;
- compound scenarios that distinguish a primary acute cause from a genuine secondary pre-existing issue;
- public-only agent payload construction that excludes difficulty, split, faults, evaluator ground truth, and expected diagnosis labels;
- an independent `BenchmarkRunner.launch()` path that can inject and stimulate scenarios without starting the agent;
- a `BenchmarkRunner.run()` path that launches a scenario, starts the real agent through `/agent/runs`, records an evaluator artifact, and restores ChaosLab in `finally`;
- failure-safe launch cleanup so setup/stimulus errors restore ChaosLab before propagating;
- deterministic replay checks for identical seeds;
- per-primitive evidence contracts across all scenarios, including union-of-evidence requirements for compound cases and healthy-baseline evidence for no-fault counterfactuals;
- a live Docker-backed Phase 6 smoke that validates representative Easy, Medium, Hard, Adversarial, Counterfactual, and Compound cases against the real simulator;
- a live autonomous-agent BenchmarkLab E2E proving an Easy N+1 scenario completes through `BenchmarkRunner.run()` with a grounded `n_plus_one_query` diagnosis and clean restoration afterward;
- ordinary cumulative CI integration so Phase 6 static integrity and the live benchmark smoke are part of the same Phase 1–6 acceptance gate.

## Scenario taxonomy and release shape

The release catalog follows the Phase 6 specification target exactly:

- **Easy — 10:** single failure, strong signal, minimal distraction;
- **Medium — 12:** single causal failure with realistic noise and required distractors;
- **Hard — 12:** delayed effects, weaker/ambiguous observations, and temporal structure;
- **Adversarial — 8:** misleading superficial correlation or controlled counterfactual structure;
- **Compound — 8:** two genuine failures with primary-vs-secondary causal labeling.

Split distribution is fixed at:

- **development: 30**;
- **validation: 10**;
- **hidden test: 10**.

Near-identical failure/template/combination structures are prevented from leaking across splits.

## Important design decisions

1. **Benchmark truth is evaluator-only.** The agent receives only the public incident payload. Ground truth, difficulty, split, injected faults, counterfactual labels, and expected diagnosis remain outside the agent request boundary.
2. **Scenario launch is independent of the agent.** `BenchmarkRunner.launch()` can reproduce a benchmark incident by itself, satisfying the exit-gate requirement that the benchmark not depend on agent execution.
3. **Cleanup is part of correctness.** `launch()` restores on failure; `run()` always restores in `finally`; live CI explicitly verifies zero active faults and healthy service behavior afterward.
4. **Structural holdouts matter more than random splits.** Split ownership is enforced for failure structures, template families, and compound combinations to reduce benchmark leakage.
5. **Temporal causality is explicit data.** Cause, distractor, and effect events carry offsets so evaluation can distinguish correlation from causal timing.
6. **Compound labels preserve causal hierarchy.** The primary root cause explains the acute incident onset while secondary root causes remain genuine but non-primary contributors.
7. **Counterfactuals are controlled variants.** The deploy/cron/latency family includes original, long-gap, no-deploy, and disabled-trigger controls for diagnosis-consistency analysis.
8. **Evidence declarations are primitive-specific.** Every injected primitive requires its own evidence family; compound cases require the union; fault-free controls require healthy-baseline/no-error evidence.
9. **Research integrity beats passing tests.** Failures exposed by live validation were fixed at the model/runner contract rather than by weakening assertions or changing labels to force success.
10. **Phase 6 is cumulative.** The ordinary `CI` workflow now includes a BenchmarkLab static job and executes the Phase 6 live benchmark smoke inside the clean-state Compose chain after the Phase 2–5 smokes.

## Defects found and repaired during live validation

Phase 6 closeout exposed two meaningful runtime defects:

- **memory-leak stimulus mismatch:** P2 memory pressure reaches the simulator restart threshold on the third 256 KiB request against a 1 MiB cap. The original four-request benchmark expected the final request to remain 503 even though the simulated process had already restarted and recovered. The catalog was corrected to stop at the deterministic P2 failure boundary rather than weakening the runtime assertion;
- **failed-launch cleanup gap:** a stimulus/injection failure in `BenchmarkRunner.launch()` could leave active ChaosLab state. `launch()` now restores before re-raising, with a regression test proving cleanup.

These repairs preserve simulator semantics and strengthen benchmark reproducibility.

## Migrations and configuration

No new Phase 6 database migration is required. Phase 6 consumes the existing Phase 1–5 backend persistence and simulator contracts.

New project configuration/CI surface:

- standalone `benchmarklab/pyproject.toml` package definition;
- dedicated `.github/workflows/phase6-benchmarklab.yml` static + live workflow;
- ordinary `.github/workflows/ci.yml` now includes a `benchmarklab` job and installs BenchmarkLab in the Compose job before the cumulative live smoke.

The existing backend migration gate still applies migrations from zero and verifies rollback/re-upgrade.

## Validation commands and gates

Phase 6 static validation:

```bash
python -m pip install -e 'benchmarklab[dev]'
ruff check benchmarklab scripts/phase6-benchmark-smoke.py
mypy benchmarklab/benchmarklab
pytest benchmarklab/tests
```

Phase 6 live validation:

```bash
docker compose down -v --remove-orphans
docker compose build
docker compose up -d
python scripts/phase6-benchmark-smoke.py
```

The live smoke verifies:

- representative Easy, Medium, Hard, Adversarial, Counterfactual, and Compound cases;
- actual injected fault presence;
- actual simulator evidence production;
- required distractor/timeline/public-payload contracts;
- deterministic replay for the same seed;
- no-fault counterfactual health;
- coexistence of both faults in a compound scenario;
- live `BenchmarkRunner.run()` → `/agent/runs` execution and grounded N+1 diagnosis;
- restoration after each scenario and after the live agent run.

Cumulative Phase 1–6 Compose sequence now includes:

```bash
python scripts/phase2-smoke.py
python scripts/phase3-mcp-smoke.py
python scripts/phase4-agent-smoke.py
python scripts/phase5-operational-smoke.py
python scripts/phase5-approval-negative-smoke.py
python scripts/phase5-rejected-matrix-smoke.py
python scripts/phase6-benchmark-smoke.py
```

The cumulative gate also verifies clean startup, migrations/schema state, persisted checkpoint/diagnosis counts, normal load generation, metrics/tool/agent endpoints, zero residual ChaosLab faults, critical-log absence, restart cleanup, and clean teardown.

## Branch validation results

### Dedicated Phase 6 workflow

Workflow run **#38** passed both jobs:

- **benchmarklab: PASS** — install, Ruff, strict mypy, unit/integrity tests, and catalog smoke;
- **live-benchmarklab: PASS** — clean Compose build, full-stack health, representative live scenario validity gate, live agent BenchmarkRunner E2E, final restoration/log inspection, and teardown.

### Cumulative CI

CI run **#100** passed all five jobs on branch head `263133d29983b44d26ef5dff8a0532470330bf58`:

- **backend: PASS** — Ruff, strict mypy, unit tests, backend/MCP/agent import/startup smoke, migration upgrade, integration tests, migration rollback/re-upgrade, and cleanup;
- **chaoslab: PASS** — Ruff, unit tests, and import smoke tests;
- **benchmarklab: PASS** — Ruff, strict mypy, unit/integrity tests, and catalog smoke;
- **frontend: PASS** — production build;
- **compose: PASS** — Compose validation/build, complete clean-state Phase 1–6 integration gate including the live BenchmarkLab/agent smoke, restart cleanup regression, log inspection, and clean teardown.

This is the branch-level cumulative proof required before documentation closeout and merge.

## Phase 6 required behavior demonstrated

- every release scenario passes typed/runtime contract validation;
- every injected primitive has required evidence declarations;
- all five difficulty tiers exist at the required counts;
- representative live validation covers every tier;
- adversarial cases contain misleading pre-effect distractors;
- compound cases preserve primary and secondary causal labels;
- every scenario has explicit timing and valid cause/effect ordering;
- counterfactual variants support controlled diagnosis-consistency experiments;
- structural split leakage is rejected;
- evaluator ground truth is excluded from agent-visible payloads;
- identical seeds replay deterministically;
- the runner launches incidents independently of the agent;
- the runner can also execute the real autonomous agent and record an evaluator artifact;
- launch/run cleanup leaves ChaosLab restored;
- the complete Phase 1–6 system passes together from a clean Compose environment.

## Known non-blocking limitations

- The initial benchmark is intentionally 50 scenarios; the Phase 6 specification suggests later expansion toward 100, but that is not part of the current exit gate.
- The deterministic simulator and deterministic agent provider are research fixtures, not evidence that these scenarios reproduce the full distribution of real production incidents.
- Hidden-test labels are present in the repository because Phase 7 will build the evaluation layer around this benchmark; Phase 6 guarantees agent-request isolation, not external benchmark secrecy from repository maintainers.
- Phase 6 establishes scenario validity and reproducibility; aggregate scoring, calibration, cost/efficiency metrics, and failure taxonomy belong to Phase 7.

## Exact Phase 7 prerequisites

After final Phase 6 closeout, Phase 7 may rely on:

- a deterministic typed 50-scenario benchmark catalog with fixed versioning and seeds;
- stable difficulty and dev/validation/hidden split labels;
- structural holdout guarantees;
- public-only agent payloads with explicit leakage checks;
- independent scenario launch and cleanup semantics;
- live-realistic fault/evidence generation through ChaosLab;
- explicit temporal, adversarial, compound, and counterfactual metadata;
- primary and secondary root-cause labels for evaluator use;
- reproducible `BenchmarkRunArtifact` records from real agent executions;
- a cumulative CI gate that validates Phases 1–6 together from clean state.

## Final closeout condition

**Pending.** The implementation/code gate is satisfied on the Phase 6 branch, but Phase 6 is not fully closed until this documentation-inclusive branch state passes both CI gates, PR #8 is merged, and the merged `main` state passes the complete Phase 1–6 cumulative gate. Only then may Phase 7 begin.
