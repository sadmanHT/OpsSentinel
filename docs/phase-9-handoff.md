# Phase 9 Handoff — Cost/Accuracy Optimization, Observability, and Human-AI System

## Status

**IN PROGRESS.** Phase 9 started from the fully closed Phase 8 `main` head `fae661fc1634aad6a3855a1dec8dcddb16a890dd`, whose final status-only cumulative CI #252 (run `34199651802`) completed successfully.

Current branch: `phase-9-cost-observability-ui`.

This document is a live implementation record. Phase 9 must not be declared complete until the full Phase 1–9 clean-state cumulative gate, frontend E2E flows, observability trace propagation, analytics cross-checks, restart/recovery checks, and CI-equivalent validation all pass together.

## Phase 9 objective

Make practical cost/accuracy/latency tradeoffs measurable and make autonomous incident investigations inspectable by humans without weakening the evidence-grounding, safety, BenchmarkLab, EvaluationLab, or ResearchLab guarantees established in earlier phases.

## Checkpoint 9.1 — Cost tracking and typed run observability

Initial implementation scope:

- preserve the existing `AgentBudget` token/cost accounting used by prior phases;
- add a typed `ModelExecutionEvent` for each reasoning-provider operation (`plan`, `update_hypotheses`, `enough_evidence`, `diagnose`, `recommend`);
- retain separate input/output token counts, estimated provider cost, model latency, success/failure status, provider identity, operation, and timestamp;
- preserve the exact inner provider `name` so Phase 8 provider-marker and treatment-isolation checks continue to observe the same experimental provider identity;
- add migration `0006_phase9_model_executions` with a durable `model_executions` table keyed to `agent_runs`;
- derive tool-call count and p50/p95 latency from the existing durable `tool_calls` records;
- derive retrieval depth from the existing durable `evidence` records;
- retain the canonical aggregate `agent_runs.token_usage` and `agent_runs.estimated_cost` as the total run accounting while exposing the new model-call breakdown separately;
- expose `GET /observability/runs/{run_id}/cost` with explicit missing values instead of silently fabricating latency/timing measurements;
- record metering write failures to application logs without replacing the original provider output or exception.

The first timing surface derives time-to-first-measured-investigation-step from the earliest model/tool observation and time-to-diagnosis from the successful `diagnose` model-execution timestamp. Time-to-verified-resolution remains explicitly unavailable at this checkpoint and will be added with the Phase 9 operational trace work.

## First-checkpoint tests

Added coverage includes:

- metered provider preserves outputs and exact provider identity;
- all five reasoning operations generate successful model-execution events;
- failed provider operations generate a failed event and re-raise the original provider error;
- p50/p95 interpolation is deterministic and empty latency sets remain explicitly missing;
- PostgreSQL integration cross-checks the Phase 9 summary against persisted `agent_runs`, `tool_calls`, `evidence`, checkpoints, and model-execution rows.

## Remaining Phase 9 scope

Checkpoint 9.1 is only the measurement foundation. Still required before Phase 9 closure:

1. cost/accuracy Pareto frontier analysis across model, tool budget, planning strategy, retrieval depth, and verification strategy;
2. complete latency analysis including time to verified resolution and aggregate p50/p95 reporting;
3. OpenTelemetry propagation across frontend → FastAPI → agent graph → MCP → simulator plus database/tool/graph instrumentation;
4. Prometheus/Grafana integration for operational metrics;
5. self-hosted Langfuse traces for LLM/tool/token/latency/evaluation/experiment metadata without making a paid API mandatory;
6. React Incident Console, investigation timeline, evidence/hypothesis separation, approval UI, and experiment dashboard;
7. frontend loading/error/agent-failure/approval/rejection/completed/compound states;
8. dashboard-to-database/evaluation cross-checks that distinguish missing data from zero;
9. representative easy, hard, adversarial, and compound incidents executed through the actual frontend from a clean environment;
10. optional small human-approval quality study if feasible, with appropriately limited conclusions;
11. exact-head Phase 1–9 cumulative regression, clean-start, restart/recovery, log inspection, persistence integrity, and CI-equivalent validation;
12. guarded merge and post-merge `main` proof before Phase 10 begins.

## Research-integrity rule

Cost, latency, accuracy, calibration, or human-study results are measurements, not preferred CI outcomes. Engineering defects must be repaired until the pipeline is correct, but benchmarks, labels, scoring rules, thresholds, experimental treatments, or observations must not be changed merely to produce a preferred Phase 9 conclusion.
