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

## Checkpoint 9.4 — Distributed OpenTelemetry propagation and privacy controls

Phase 9.4 adds an opt-in distributed trace path across the real browser and investigation runtime without exposing hidden benchmark state or serializing MCP arguments into trace attributes.

Implementation scope:

- browser tracing is disabled during the normal frontend path and enabled only when the Incident Console is opened with `?otel=1`;
- the browser creates the root span `frontend.start_investigation`, exports OTLP/HTTP to the local collector, and injects W3C `traceparent` into the same public `POST /api/agent/runs` request used by the proof UI;
- Vite proxies `/api` to the backend so the browser propagation proof does not require broadening backend CORS policy;
- the proof starts a public checkout investigation and requests `pause_after: "store_evidence"`, forcing the graph through planning, tool selection, a real MCP call, and evidence storage without entering remediation or approval paths;
- backend manual spans include `agent.investigation`, `agent.node.<node>`, and `mcp.tool.<tool>` while avoiding scenario identity, hidden simulator truth, and serialized tool arguments;
- backend and ChaosLab FastAPI/HTTPX auto-instrumentation preserve trace continuity while overwriting request-target attributes (`url.full`, `url.query`, `http.url`, `http.target`) with `[redacted]` and setting `opssentinel.http.request_target_redacted`;
- ChaosLab resources remain service-isolated, including `chaoslab-checkout` for the representative proof;
- the collector accepts OTLP gRPC/HTTP and exposes browser CORS only for the local frontend origins used by the proof;
- `scripts/phase9-otel-verify.py` scopes verification to the browser-generated 32-hex trace ID and requires the frontend, backend, and checkout simulator resources, agent/MCP spans, backend client span, ChaosLab server span, request-target redaction evidence, and absence of known hidden-state/tool-argument canaries;
- raw collector output is never uploaded as a workflow artifact; the retained artifact is only the compact verifier summary.

### Phase 9.4 validation coverage

The dedicated `Phase 9 OpenTelemetry` workflow contains two gates:

1. an integrity job covering Ruff, strict backend mypy, backend/ChaosLab tracing tests, frontend production build, browser-proof syntax, and Compose observability-profile validation;
2. a clean-state live job that installs Chromium, starts the traced Compose stack, drives the real frontend with Playwright, verifies the browser → FastAPI → agent graph → MCP → ChaosLab trace chain, confirms the paused run is persisted, checks no active faults or critical backend/ChaosLab logs remain, retains only the safe proof JSON, and tears the environment down.

A validated pre-handoff checkpoint on commit `1bd91dd26ade7abe9e71eef643132c866e0668d0` completed the push workflow run `34225511683` successfully. Its safe artifact was:

- artifact name: `phase9-otel-distributed-trace`
- artifact ID: `10055626090`
- artifact digest: `sha256:561a1463c7d60a702d868c6fdfc6b2e76b5e94e298d96cb7eb60109a0dd4ba32`
- proof trace ID: `87f631429b8a552ce6b5ecdf96a54cc7`
- proof run ID: `10cd886c-6311-43e4-a22a-854848896daf`
- observed MCP span: `mcp.tool.query_metrics`
- observed required services: `opssentinel-frontend`, `opssentinel-backend`, `chaoslab-checkout`
- observed required spans: `frontend.start_investigation`, `agent.investigation`, `agent.node.execute_tool`, `agent.node.store_evidence`
- privacy checks: no forbidden hidden-state canaries, no serialized tool arguments, no unredacted request-target attributes, and request-target redaction present in both backend and ChaosLab trace blocks.

This is pre-handoff evidence rather than the final Phase 9.4 acceptance head: updating this document necessarily advances the branch, so the dedicated OpenTelemetry workflow and cumulative Phase 6–9 regression matrix must pass again on the new exact head before the checkpoint can be accepted.

## Remaining Phase 9 scope

Checkpoint 9.1 established the measurement foundation and Checkpoint 9.4 now has a working distributed-trace implementation, but Phase 9 remains open. Still required before Phase 9 closure:

1. finish and preserve the accepted cost/accuracy Pareto analysis across the implemented model/tool-budget/planning/retrieval/verification treatment surfaces;
2. finish and preserve the latency analysis, including any explicitly measurable verified-resolution timing and aggregate p50/p95 reporting;
3. Prometheus/Grafana integration for operational metrics;
4. self-hosted Langfuse traces for LLM/tool/token/latency/evaluation/experiment metadata without making a paid API mandatory;
5. React Incident Console, investigation timeline, evidence/hypothesis separation, approval UI, and experiment dashboard;
6. frontend loading/error/agent-failure/approval/rejection/completed/compound states;
7. dashboard-to-database/evaluation cross-checks that distinguish missing data from zero;
8. representative easy, hard, adversarial, and compound incidents executed through the actual frontend from a clean environment;
9. optional small human-approval quality study if feasible, with appropriately limited conclusions;
10. exact-head Phase 1–9 cumulative regression, clean-start, restart/recovery, log inspection, persistence integrity, and CI-equivalent validation;
11. guarded merge and post-merge `main` proof before Phase 10 begins.

## Research-integrity rule

Cost, latency, accuracy, calibration, or human-study results are measurements, not preferred CI outcomes. Engineering defects must be repaired until the pipeline is correct, but benchmarks, labels, scoring rules, thresholds, experimental treatments, or observations must not be changed merely to produce a preferred Phase 9 conclusion.
