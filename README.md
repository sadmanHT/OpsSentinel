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
- ⏭️ **Phase 2 — ChaosLab Production Simulator:** next implementation phase.
- Phases 3–10 remain gated behind successful completion of all prior phases.

Phase 1 was validated with linting, strict typing, unit tests, PostgreSQL integration tests, migration upgrade/downgrade/re-upgrade, frontend production build, Compose validation/image builds, and a clean-state full-container smoke test. See `docs/phase-1-handoff.md` for the recorded validation evidence and defects that were discovered and repaired during the gate.

## Phase 1 stack

- Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic
- PostgreSQL + pgvector, Redis
- React + TypeScript + Vite
- Docker Compose
- pytest, ruff, mypy, GitHub Actions

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

The backend API is available at `http://localhost:8000` and exposes `GET /health`.

## Database migrations

```bash
make db-upgrade
```

The initial migration creates the persistence contract needed by later phases: incidents, runs, evidence, hypotheses, tool calls, approvals, diagnoses, evaluation runs/scores, and experiment metadata.

## Research integrity

Hypotheses are recorded before experiments. The software must be repaired until required validation passes, but experimental code, labels, tests, or benchmark ground truth must never be modified merely to force a preferred research result. Negative or surprising findings are valid when the experiment is correct.

See `docs/architecture.md`, `docs/research-hypotheses.md`, and `docs/phase-1-handoff.md`.
