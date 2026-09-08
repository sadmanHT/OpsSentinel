# OpsSentinel

**An experimental platform for evaluating autonomous AI incident-response agents.**

OpsSentinel studies a central question: **when does additional agent reasoning improve production-incident diagnosis, and when does it cause over-investigation, anchoring, wasted tool calls, overconfidence, or false conclusions?**

The project is implemented in ten gated phases. A phase is complete only after its new behavior and every previously completed phase pass cumulative unit, integration, failure-path, regression, clean-start, restart/recovery, and CI-equivalent validation.

## Four-system architecture

1. **ChaosLab** — reproducible production-incident simulator and modular fault injection.
2. **OpsSentinel Agent Runtime** — LangGraph-based autonomous investigator using constrained tools through MCP.
3. **Benchmark & Evaluation Laboratory** — realistic, difficult, adversarial, compound, temporal, and counterfactual evaluation.
4. **Research & Observability Layer** — accuracy, calibration, efficiency, cost, safety, causal reasoning, traces, dashboards, and failure analysis.

## Current implementation status

- ✅ **Phase 1 — Foundation, Contracts, and Reproducible Development Environment:** cumulative gate passed.
- ✅ **Phase 2 — ChaosLab Production Simulator:** cumulative gate passed and revalidated on `main`.
- ✅ **Phase 3 — MCP Investigation Tooling and Safety Boundary:** cumulative gate passed.
- ✅ **Phase 4 — First Autonomous Agent and Evidence-Driven Reasoning:** cumulative gate passed.
- ✅ **Phase 5 — Safety, Human Approval, Verification, and Fault Recovery:** fully closed; PR #7 merged and the complete Phase 1–5 cumulative gate passed on `main`. See `docs/phase-5-handoff.md`.
- ✅ **Phase 6 — BenchmarkLab:** fully closed; PR #8 merged and the complete post-merge Phase 1–6 cumulative gate passed on `main`. See `docs/phase-6-handoff.md`.
- ✅ **Phase 7 — Evaluation Engine, Calibration, and Failure Taxonomy:** fully closed after guarded PR #9 merge and post-merge cumulative validation. See `docs/evaluationlab.md` and `docs/phase-7-handoff.md`.
- ✅ **Phase 8 — Controlled Research Experiments and Architecture Comparisons:** fully closed after guarded PR #10 merge and successful post-merge cumulative validation. Null and negative findings remain first-class results. See `docs/phase-8-handoff.md`.
- ✅ **Phase 9 — Cost/Accuracy Optimization, Observability, and Human-AI System:** fully closed after guarded PR #11 merge, successful post-merge cumulative validation on `main`, and the final status-only closure safeguard. See `docs/phase-9-handoff.md`.
- **Phase 10 is the next gated phase.** It is unblocked only because Phases 1–9 are cumulatively closed; its own work must satisfy the same phase-gated acceptance discipline.

## Stack in use

- Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic
- PostgreSQL + pgvector, Redis
- Docker Compose
- React + TypeScript + Vite
- OpenTelemetry
- Prometheus + Grafana
- self-hosted Langfuse v4
- pytest, pytest-asyncio, Ruff, mypy, Playwright, GitHub Actions

## Quick start

```bash
cp .env.example .env
make setup
make test
make frontend-build
```

For the full containerized environment:

```bash
docker compose down -v
make clean-start
```

Useful endpoints after startup:

- OpsSentinel backend: `http://localhost:8000/health`
- MCP safety boundary: `http://localhost:8000/mcp/health`
- MCP tool registry: `http://localhost:8000/mcp/tools`
- Incident Console: `http://localhost:5173/`
- run cost/latency summary: `http://localhost:8000/observability/runs/{run_id}/cost`
- persisted experiment dashboard API: `http://localhost:8000/observability/experiments`
- simulated gateway: `http://localhost:8080/health`
- ChaosLab controller: `http://localhost:8100/health` (test harness only; never exposed to agents)
- checkout telemetry: `http://localhost:8101/telemetry`
- inventory telemetry: `http://localhost:8102/telemetry`
- payment telemetry: `http://localhost:8103/telemetry`
- worker telemetry: `http://localhost:8104/telemetry`

Phase-specific operational smoke flows are exercised by cumulative CI and dedicated exact-head workflows. Phase 5 covers approval/rejection, persisted resume, verification, transient-tool recovery, major MCP failure paths, and zero executed R3 operations. Phase 6 adds the deterministic 50-scenario BenchmarkLab catalog and live benchmark-to-agent E2E. Phase 7 adds deterministic evaluation, calibration, persisted evaluator/experiment records, and live counterfactual causal-consistency checks. Phase 8 adds controlled real-agent experiments for architecture, investigation budget, tool order, active verification, temporal reasoning, and compound stopping while preserving null/negative findings.

Phase 9 adds durable model/tool/token/cost/latency accounting; an 80-trial sampled cost/accuracy Pareto analysis; live latency timing including verified-resolution semantics; browser-to-simulator OpenTelemetry; Prometheus/Grafana operational and research monitoring; a self-hosted Langfuse stack with safe agent/tool/generation traces and post-hoc evaluator scores; the React Incident Console with explicit human approval boundaries; a persisted EvaluationLab-backed experiment dashboard; and clean-state Playwright runs for easy, hard, adversarial, and compound BenchmarkLab incidents. Missing measurements remain missing, legitimate zero token/$0 local-provider measurements remain zero, and benchmark truth remains outside the agent/browser runtime.

## Research integrity

Hypotheses are recorded before experiments. The software must be repaired until required validation passes, but experimental code, labels, tests, scoring rules, benchmark ground truth, or reported observations must never be modified merely to force a preferred research result. Negative, null, or surprising findings are valid when the experiment is correct.

See `docs/architecture.md`, `docs/research-hypotheses.md`, `docs/phase-1-handoff.md`, `docs/chaoslab.md`, `docs/phase-2-handoff.md`, `docs/mcp-safety.md`, `docs/phase-3-handoff.md`, `docs/phase-4-handoff.md`, `docs/phase-5-handoff.md`, `docs/phase-6-handoff.md`, `docs/evaluationlab.md`, `docs/phase-7-handoff.md`, `docs/phase-8-handoff.md`, and `docs/phase-9-handoff.md`.
