# Phase 8 Handoff — Controlled Research Experiments and Architecture Comparisons

## Status

**In progress.** Phase 8 has started from closed Phase 7 main head `40467b27085130c110098cac5077fb62dee4e5aa` on branch `phase-8-controlled-research`. This record is intentionally not a completion claim.

## Current implementation increment

The first Phase 8 increment establishes controlled-experiment bookkeeping before any research result is interpreted:

- a standalone typed `researchlab/` package;
- six experiment kinds matching the Phase 8 specification;
- explicit research configuration dimensions for architecture, tool budget, tool order, evidence/verification mode, temporal reasoning, and compound stopping strategy;
- controlled-plan validation that rejects cells which accidentally vary non-target dimensions;
- the required investigation budgets 5/10/15/20;
- difficulty-aware experiment cells, with compound handling restricted to compound incidents;
- deterministic trial UUIDs and seeds derived without Python process hash state;
- public scenario references containing split/difficulty identity but no benchmark ground truth;
- split mismatch rejection before any trial can execute;
- trial records for running/completed/failed/interrupted states;
- resumable orchestration that skips completed trials while safely retrying interrupted or incomplete trials;
- retention fields for evaluator run id, agent run id, raw trajectory, and numeric scores;
- dedicated Phase 8 static/unit CI and a controlled-plan smoke.

## Research integrity

The six configurations encode comparisons; they do not encode conclusions. H1–H5 remain hypotheses. No result such as “planning helps” or “more investigation hurts” is treated as a CI target. Research-performance measurements will be accepted as observed once the execution pipeline is validated.

## Current validation

Local interpreter validation before the first branch commit:

- Python syntax parse: PASS;
- ResearchLab unit/integrity tests: **11 PASS**;
- split-leakage negative test: PASS;
- interruption/resume test: PASS.

Local Ruff/mypy binaries are not available in the execution sandbox; the dedicated GitHub Actions workflow is the authoritative Python 3.11 lint/type gate and must pass before this increment is accepted.

## Next implementation steps

1. wire public BenchmarkLab scenario metadata into `ScenarioRef` without ground-truth leakage;
2. add durable experiment-journal persistence using the canonical Phase 7 research schema;
3. expose controlled agent research variants, beginning with reactive ReAct versus the existing explicit planner;
4. run the required tiny live smoke and prove each configuration changes runtime behavior as intended;
5. add investigation-budget, tool-order, verification, temporal-reasoning, and unresolved-evidence runtime controls;
6. execute several complete reproducible experiments with raw trajectories and measured results retained;
7. fold Phase 8 into the cumulative clean-state Phase 1–8 gate before any completion claim.
