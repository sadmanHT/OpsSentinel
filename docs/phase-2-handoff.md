# Phase 2 Handoff Record

## Status

**Phase 2 cumulative gate passed on the implementation branch.**

Phase 2 was not marked complete when the simulator first ran. Failures discovered by linting, package smoke checks, and simulator review were treated as blocking defects, corrected at the source, and the cumulative Phase 1 + Phase 2 validation chain was rerun. GitHub Actions run `34011015683` completed successfully with all required jobs green: `backend`, `chaoslab`, `frontend`, and `compose`.

## Implemented outcome

Phase 2 adds **ChaosLab**, a reproducible and manually diagnosable production-incident simulator that later MCP tools and benchmark scenarios can observe without receiving hidden fault-control state.

Implemented topology:

- gateway service;
- checkout API backed by PostgreSQL;
- inventory API backed by PostgreSQL;
- payment API;
- background worker;
- Redis-backed scenario-control state;
- ChaosLab controller;
- existing OpsSentinel backend and frontend retained from Phase 1.

Implemented simulator capabilities:

- health endpoints for every service;
- structured JSON request telemetry;
- Prometheus-compatible metrics;
- human-readable `/telemetry` snapshots;
- deterministic normal, burst, and sustained load profiles;
- targetable service-specific load generation;
- Python `ChaosLabClient` with `inject`, `status`, `restore`, and `restore_all` lifecycle;
- fixed-seed fault configuration and explicit generation tracking;
- controlled restoration and restart semantics;
- target validation so unsupported fault/service combinations fail instead of becoming silent no-op scenarios.

## Five Phase 2 fault primitives

### 1. N+1 database query

- target: checkout;
- healthy `/orders` path performs one batched query;
- injected path performs many per-order/per-product queries;
- request remains successful while query count and latency rise;
- restore returns query count to the healthy baseline.

### 2. Connection leak

- targets: checkout or inventory;
- simulated active connection count grows across requests;
- configured capacity is eventually exhausted;
- requests then fail with a controlled pool-timeout `503`;
- restore returns the simulated connection state to zero.

### 3. Disk exhaustion

- bounded files are written inside the service container only;
- observable simulated disk usage rises progressively;
- requests eventually fail with a controlled `507` / no-space symptom;
- restore removes simulator artifacts and returns usage to zero.

### 4. Broken environment/configuration

- target: payment;
- payment changes from success to authentication/configuration rejection;
- gateway surfaces the dependency failure;
- unrelated inventory behavior remains healthy;
- restore returns payment and gateway behavior to baseline.

### 5. Memory leak

- bounded process-local memory is retained progressively;
- observable retained bytes increase across requests;
- the configured threshold triggers a controlled simulated restart and `503`;
- retained bytes clear while the restart counter remains observable;
- restore returns subsequent requests to baseline.

## Severity and safety semantics

Severity is monotonic: `P1` reaches progressive failure thresholds earlier than `P2`, and `P2` earlier than `P3`. Unit tests lock this relationship in.

The simulator intentionally reproduces diagnostic signals without destabilizing the host or CI runner:

- memory growth is bounded;
- disk writes are bounded and container-local;
- connection exhaustion is represented by a bounded simulated pool counter;
- destructive host behavior is not used.

## Restart semantics

ChaosLab separates **scenario intent** from **ephemeral process artifacts**:

- active fault definitions are stored in Redis and intentionally survive service-container restart;
- retained memory, simulated connection counters, and other process-local state reset when the service restarts;
- explicit controller restoration removes the scenario intent and resets the target service.

The cumulative CI gate verifies this behavior with active memory-leak and connection-leak scenarios rather than testing only an already-clean restart.

## Validation evidence

### ChaosLab unit/static validation

GitHub Actions run `34011015683`:

- ChaosLab dependency installation: passed;
- Ruff: passed;
- ChaosLab unit suite: **13 passed**;
- package import/API smoke tests: passed.

The unit suite covers:

- Pydantic fault contracts;
- controller target validation;
- client request/response contracts;
- fault-store injection and restoration;
- reinjection generation increments;
- restore-non-active idempotency;
- observable cleanup;
- disk severity progression;
- memory severity progression and bounded allocation;
- connection-pool exhaustion.

### Phase 1 regression validation

The same run re-executed Phase 1 guarantees and passed:

- backend dependency installation;
- Ruff;
- strict mypy;
- backend unit tests;
- FastAPI import/startup smoke test;
- Alembic upgrade from zero;
- PostgreSQL integration tests;
- Alembic downgrade to base and re-upgrade to head;
- frontend dependency installation and production build.

### Clean-state full-system integration validation

The `compose` job passed:

- base Compose validation;
- test Compose validation;
- full image build;
- `docker compose down -v --remove-orphans` clean start;
- complete containerized environment startup;
- OpsSentinel backend health;
- ChaosLab controller health;
- gateway, checkout, inventory, payment, and worker health;
- Phase 1 migrated database-table verification;
- live Phase 2 five-fault smoke suite;
- real `normal` load profile against the live gateway with 20 requests and zero errors;
- Prometheus metric presence checks;
- backend and simulator log inspection for `Traceback`, unhandled exception, or `CRITICAL` output;
- active-fault container restart regression;
- explicit fault restoration after restart;
- clean teardown including volumes and orphans.

## Live fault smoke coverage

`scripts/phase2-smoke.py` proves baseline → inject → observe → restore → baseline behavior and includes:

- unknown fault rejection;
- unknown service rejection;
- unsupported fault/service rejection;
- safe restoration of a non-active fault;
- double injection with generation increment;
- N+1 query-count and latency degradation plus repeatable causal structure;
- connection leak progression to pool timeout;
- disk usage progression to write failure;
- broken payment configuration while unrelated inventory remains healthy;
- progressive memory leak and controlled restart;
- restoration of all five faults to healthy behavior.

## Manual diagnosability

`docs/chaoslab.md` documents the observable evidence path for every fault without using controller ground truth. The live integration suite confirms those observables are actually emitted. A future investigator can distinguish each Phase 2 fault using request behavior, telemetry, metrics, and service relationships rather than the hidden injection state.

## Defects discovered and fixed during the Phase 2 gate

1. **Severity inversion in progressive faults.** Early implementation used a threshold scale that could make `P1` disk/memory incidents fail later than lower-severity incidents. The threshold model was corrected and monotonic-severity tests were added.
2. **Unsupported fault/service combinations could create meaningless scenarios.** Controller-side target validation was added so incompatible pairs fail with `422` rather than silently producing a no-op fault.
3. **ChaosLab lint defects.** CI identified an outdated `typing.Iterator` import and several overlong source lines. The source was corrected without weakening Ruff or changing the lint boundary.
4. **Monorepo import-smoke path shadowing.** Running a package import from repository root selected the project directory namespace before the installed inner package. The smoke check was corrected to run from the ChaosLab package working directory—the same context used by the container and package project—without adding import hacks or weakening the check.

These defects are retained here as evidence that the cumulative gate was used to find and repair problems rather than treating first-pass implementation as complete.

## Important design decisions

- ChaosLab's controller is scenario-control infrastructure and **must not be exposed to future investigation agents**, because it contains hidden injected-fault state and would leak benchmark ground truth.
- `/telemetry`, `/metrics`, application request behavior, logs, database observations, and later MCP diagnostic interfaces are the legal investigation surfaces.
- Fault artifacts are deliberately bounded so repeated evaluation cannot intentionally exhaust the host.
- Fault state has explicit type, service, severity, seed, configuration, and generation metadata so later benchmark scenarios can be reproduced and versioned.
- Phase 2 does not implement the AI investigator. LangGraph/MCP agent behavior begins in later phases.

## Commands represented by the cumulative gate

```bash
ruff check backend
mypy backend/app
pytest backend/tests -m 'not integration'
cd backend && alembic upgrade head
cd backend && pytest tests -m integration
cd backend && alembic downgrade base && alembic upgrade head

ruff check chaoslab
pytest chaoslab/tests

cd frontend && npm run build

docker compose -f docker-compose.yml config
docker compose -f docker-compose.yml -f docker-compose.test.yml config
docker compose build
docker compose down -v --remove-orphans
docker compose up -d --build
python scripts/phase2-smoke.py
```

## Known non-blocking phase boundaries

- MCP investigation servers are intentionally not implemented yet; they are Phase 3.
- The autonomous LangGraph investigator is intentionally not implemented yet; it is Phase 4.
- Benchmark difficulty/adversarial/compound scenario generation belongs to Phase 6.
- OpenTelemetry/Langfuse/Grafana research observability is a later-phase responsibility.
- ChaosLab currently establishes deterministic fault primitives rather than a frozen research benchmark.

These are planned boundaries, not failures of the Phase 2 contract.

## Next-phase prerequisite

Phase 3 — **MCP Investigation Tooling and Safety Boundary** — may rely on:

- the complete Phase 1 foundation;
- a reproducible clean Docker Compose environment;
- healthy gateway, checkout, inventory, payment, and worker services;
- controller-managed fault injection and restoration;
- five manually diagnosable fault primitives;
- structured logs, Prometheus metrics, and observable telemetry;
- deterministic load generation;
- bounded simulator behavior;
- fault target validation;
- stable restart/restoration semantics;
- cumulative CI enforcement of all Phase 1 + Phase 2 behavior.

Any Phase 3 change that breaks these behaviors is a regression and must be repaired before Phase 3 can be declared complete.
