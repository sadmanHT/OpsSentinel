# OpsSentinel

**An experimental platform for evaluating autonomous AI incident-response agents.**

OpsSentinel studies a central question: **when does additional agent reasoning improve production-incident diagnosis, and when does it cause over-investigation, anchoring, wasted tool calls, overconfidence, or false conclusions?**

The project is implemented in ten gated phases. A phase is complete only after its new behavior and every previously completed phase pass cumulative unit, integration, failure-path, regression, clean-start, restart/recovery, and CI-equivalent validation.

## Four-system architecture

1. **ChaosLab** — reproducible production-incident simulator and modular fault injection.
2. **OpsSentinel Agent Runtime** — LangGraph-based autonomous investigator using constrained tools through MCP.
3. **Benchmark & Evaluation Laboratory** — realistic, difficult, adversarial, compound, temporal, and counterfactual evaluation.
4. **Research & Observability Layer** — accuracy, calibration, efficiency, cost, safety, causal reasoning, traces, and failure analysis.

## Current implementation status

- ✅ **Phase 1 — Foundation, Contracts, and Reproducible Development Environment:** cumulative gate passed.
- ✅ **Phase 2 — ChaosLab Production Simulator:** cumulative gate passed and revalidated on `main`.
- ✅ **Phase 3 — MCP Investigation Tooling and Safety Boundary:** cumulative gate passed.
- ✅ **Phase 4 — First Autonomous Agent and Evidence-Driven Reasoning:** cumulative gate passed.
- ✅ **Phase 5 — Safety, Human Approval, Verification, and Fault Recovery:** fully closed; PR #7 merged and the complete Phase 1–5 cumulative gate passed on `main`. See `docs/phase-5-handoff.md`.
- ✅ **Phase 6 — BenchmarkLab:** fully closed; PR #8 merged and the complete post-merge Phase 1–6 cumulative gate passed on `main`. See `docs/phase-6-handoff.md`.
- ✅ **Phase 7 — Evaluation Engine, Calibration, and Failure Taxonomy:** fully closed after guarded PR #9 merge and post-merge cumulative validation. See `docs/evaluationlab.md` and `docs/phase-7-handoff.md`.
- ✅ **Phase 8 — Controlled Research Experiments and Architecture Comparisons:** fully closed after guarded PR #10 merge at `e893ca7a58f0af3eb71825488ac7fb2d0c9a8232` and successful post-merge cumulative CI #250. All six controlled campaigns retain their measured null/negative findings. See `docs/phase-8-handoff.md`.
- 🟡 **Phase 9 — Cost/Accuracy Optimization, Observability, and Human-AI System:** in progress on `phase-9-cost-observability-ui`; the first checkpoint adds typed per-run model/tool/retrieval/cost/latency observability and durable model-execution metering. See `docs/phase-9-handoff.md`.
- Phase 10 remains gated behind full Phase 9 merge/post-merge closure and its own cumulative completion gate.

## Stack in use

- Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic
- PostgreSQL + pgvector, Redis
- Docker Compose
- React + TypeScript + Vite
- pytest, pytest-asyncio, ruff, mypy, GitHub Actions
- Prometheus-compatible ChaosLab service metrics

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
- Phase 9 run cost summary: `http://localhost:8000/observability/runs/{run_id}/cost`
- simulated gateway: `http://localhost:8080/health`
- ChaosLab controller: `http://localhost:8100/health` (test harness only; never exposed to agents)
- checkout telemetry: `http://localhost:8101/telemetry`
- inventory telemetry: `http://localhost:8102/telemetry`
- payment telemetry: `http://localhost:8103/telemetry`
- worker telemetry: `http://localhost:8104/telemetry`

Phase-specific operational smoke flows are exercised by the cumulative CI/Compose gate. Phase 5 includes approval/rejection, persisted resume, verification, transient-tool recovery, all-major-MCP-tool failure coverage, and zero executed R3 operations. Phase 6 adds a deterministic 50-scenario BenchmarkLab catalog, structural holdouts, temporal/adversarial/counterfactual/compound cases, leakage and reproducibility checks, independent scenario launch/cleanup, and a live benchmark-to-agent E2E. Phase 7 adds deterministic RCA/compound/evidence/efficiency/safety scoring, confidence calibration with Brier/ECE/reliability diagrams, persisted evaluation/failure/experiment records, five-tier live measurement, and a four-variant live counterfactual causal-consistency experiment. Phase 8 adds ResearchLab-controlled real-agent experiments for architecture, investigation budget, tool order, active verification, temporal reasoning, and compound stopping; treatment isolation is fail-closed, raw trajectories are retained, and performance remains descriptive rather than a CI target. Phase 9 now adds the first durable per-run model-execution and cost/latency measurement foundation; the Pareto, OpenTelemetry/Langfuse, Grafana, React investigation UI, and human-AI study work remains gated behind later Phase 9 checkpoints. All accumulated phases continue to be exercised together in the cumulative clean-state gate.

## Research integrity

Hypotheses are recorded before experiments. The software must be repaired until required validation passes, but experimental code, labels, tests, scoring rules, or benchmark ground truth must never be modified merely to force a preferred research result. Negative, null, or surprising findings are valid when the experiment is correct.

See `docs/architecture.md`, `docs/research-hypotheses.md`, `docs/phase-1-handoff.md`, `docs/chaoslab.md`, `docs/phase-2-handoff.md`, `docs/mcp-safety.md`, `docs/phase-3-handoff.md`, `docs/phase-4-handoff.md`, `docs/phase-5-handoff.md`, `docs/phase-6-handoff.md`, `docs/evaluationlab.md`, `docs/phase-7-handoff.md`, `docs/phase-8-handoff.md`, and `docs/phase-9-handoff.md`.
