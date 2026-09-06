# OpsSentinel

**An experimental platform for evaluating autonomous AI incident-response agents.**

OpsSentinel studies a central question: **when does additional agent reasoning improve production-incident diagnosis, and when does it cause over-investigation, anchoring, wasted tool calls, overconfidence, or false conclusions?**

The project is implemented in ten gated phases. A phase is complete only after its new behavior and every previously completed phase pass cumulative unit, integration, failure-path, regression, clean-start, and CI-equivalent validation.

## Four-system architecture

1. **ChaosLab** — reproducible production-incident simulator and modular fault injection.
2. **OpsSentinel Agent Runtime** — LangGraph-based autonomous investigator using constrained tools through MCP.
3. **Benchmark & Evaluation Laboratory** — realistic, difficult, adversarial, compound, temporal, and counterfactual evaluation.
4. **Research & Observability Layer** — accuracy, calibration, efficiency, cost, safety, causal reasoning, traces, and failure analysis.

## Current implementation status

- ✅ **Phase 1 — Foundation, Contracts, and Reproducible Development Environment:** cumulative gate passed.
- ✅ **Phase 2 — ChaosLab Production Simulator:** cumulative gate passed and revalidated on `main`.
- 🚧 **Phase 3 — MCP Investigation Tooling and Safety Boundary:** implementation branch in progress.
- Phases 4–10 remain gated behind successful completion of all prior phases.

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
- simulated gateway: `http://localhost:8080/health`
- ChaosLab controller: `http://localhost:8100/health` (test harness only; never exposed to agents)
- checkout telemetry: `http://localhost:8101/telemetry`
- inventory telemetry: `http://localhost:8102/telemetry`
- payment telemetry: `http://localhost:8103/telemetry`
- worker telemetry: `http://localhost:8104/telemetry`

Run the complete Phase 2 simulator smoke suite against a running environment:

```bash
make phase2-smoke
```

Phase 3 adds a controlled logical MCP registry for logs, metrics, read-only SQL, Git/deployment inspection, documentation search, and allowlisted diagnostics. The ChaosLab controller remains outside the legal agent surface. See `docs/mcp-safety.md` and `docs/phase-3-handoff.md`.

## Research integrity

Hypotheses are recorded before experiments. The software must be repaired until required validation passes, but experimental code, labels, tests, or benchmark ground truth must never be modified merely to force a preferred research result. Negative or surprising findings are valid when the experiment is correct.

See `docs/architecture.md`, `docs/research-hypotheses.md`, `docs/phase-1-handoff.md`, `docs/chaoslab.md`, `docs/phase-2-handoff.md`, `docs/mcp-safety.md`, and `docs/phase-3-handoff.md`.
