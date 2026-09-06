# OpsSentinel

**An experimental platform for evaluating autonomous AI incident-response agents.**

OpsSentinel studies a central question: **when does additional agent reasoning improve production-incident diagnosis, and when does it cause over-investigation, anchoring, wasted tool calls, overconfidence, or false conclusions?**

The project is implemented in ten gated phases. A phase is complete only after its new behavior and every previously completed phase pass cumulative unit, integration, failure-path, regression, clean-start, and CI-equivalent validation.

## Four-system architecture

1. **ChaosLab** — reproducible production-incident simulator and modular fault injection.
2. **OpsSentinel Agent Runtime** — LangGraph-based autonomous investigator using constrained MCP tools.
3. **Benchmark & Evaluation Laboratory** — realistic, difficult, adversarial, compound, temporal, and counterfactual evaluation.
4. **Research & Observability Layer** — accuracy, calibration, efficiency, cost, safety, causal reasoning, traces, and failure analysis.

## Current implementation status

- ✅ **Phase 1 — Foundation, Contracts, and Reproducible Development Environment:** cumulative gate passed.
- ✅ **Phase 2 — ChaosLab Production Simulator:** cumulative Phase 1 + Phase 2 gate passed on the implementation branch.
- ⏭️ **Phase 3 — MCP Investigation Tooling and Safety Boundary:** next implementation phase after Phase 2 is merged and revalidated on `main`.
- Phases 4–10 remain gated behind successful completion of all prior phases.

## Stack in use

- Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic
- PostgreSQL + pgvector, Redis
- Docker Compose
- React + TypeScript + Vite
- pytest, pytest-asyncio, ruff, mypy, GitHub Actions
- Prometheus-compatible ChaosLab service metrics

## ChaosLab Phase 2

The current simulator includes:

- gateway, checkout, inventory, payment, and worker services;
- PostgreSQL-backed healthy and N+1 data-access paths;
- Redis-backed scenario-control state;
- five bounded fault primitives: N+1 query, connection leak, disk exhaustion, broken configuration, and memory leak;
- monotonic `P1` / `P2` / `P3` severity semantics;
- structured request logs, Prometheus metrics, and human-readable telemetry;
- deterministic normal, burst, and sustained load profiles;
- validated inject/status/restore/restore-all lifecycle;
- clean restart semantics separating persistent scenario intent from process-local artifacts.

The ChaosLab controller is scenario-control infrastructure and must **not** be exposed to future investigation agents because it contains hidden injected-fault state. Phase 3 MCP tools will expose legal observability surfaces instead.

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
- simulated gateway: `http://localhost:8080/health`
- ChaosLab controller: `http://localhost:8100/health`
- checkout telemetry: `http://localhost:8101/telemetry`
- inventory telemetry: `http://localhost:8102/telemetry`
- payment telemetry: `http://localhost:8103/telemetry`
- worker telemetry: `http://localhost:8104/telemetry`

Run the complete Phase 2 simulator smoke suite against a running environment:

```bash
make phase2-smoke
```

Run the ChaosLab unit suite:

```bash
make chaoslab-test
```

## Phase 2 validation

The successful Phase 2 implementation-branch gate includes:

- Phase 1 backend Ruff, strict mypy, unit, migration, and PostgreSQL integration regression checks;
- frontend production build;
- ChaosLab Ruff and **13 unit tests**;
- package import smoke checks;
- base/test Compose validation and complete image build;
- clean-state full-system startup;
- live baseline → fault → symptom → restore validation for all five faults;
- live normal load generation against the gateway;
- metrics and structured-log inspection;
- active-fault container restart regression;
- clean teardown.

See `docs/phase-2-handoff.md` for exact gate evidence and defects found/fixed during implementation.

## Research integrity

Hypotheses are recorded before experiments. The software must be repaired until required validation passes, but experimental code, labels, tests, or benchmark ground truth must never be modified merely to force a preferred research result. Negative or surprising findings are valid when the experiment is correct.

See `docs/architecture.md`, `docs/research-hypotheses.md`, `docs/phase-1-handoff.md`, `docs/chaoslab.md`, and `docs/phase-2-handoff.md`.
