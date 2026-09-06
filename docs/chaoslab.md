# ChaosLab Production Simulator

ChaosLab is OpsSentinel's reproducible production-incident simulator. It exists independently of the AI agent so incidents can be validated manually and later used as controlled experimental inputs.

The controller is a **scenario-control boundary**, not an investigation surface. Future OpsSentinel agents must never receive controller access because active fault definitions reveal benchmark ground truth.

## Topology

```text
Gateway
├── Checkout API ── PostgreSQL
├── Inventory API ─ PostgreSQL
├── Payment API
└── Background Worker

Shared control state: Redis DB 1
Fault injection: ChaosLab Controller
```

All service requests emit structured JSON request-completion logs and expose Prometheus-compatible `/metrics` plus a human-readable `/telemetry` snapshot. `/telemetry` contains observations only; it does not identify the injected fault or ground-truth root cause.

## Safe simulation boundaries

ChaosLab produces production-like symptoms without destabilizing the host or CI runner:

- disk exhaustion writes only small, bounded files inside the service container;
- memory leaks retain a bounded buffer and trigger a controlled simulated restart event instead of intentionally OOM-killing the host;
- connection leaks use a bounded simulated pool counter instead of exhausting the real PostgreSQL server;
- restoration clears process-local fault artifacts;
- container replacement clears process-local artifacts by construction.

These boundaries preserve diagnostic signals while keeping repeated experiments safe and reproducible.

## Controller API and Python client

The controller exposes:

- `POST /faults/inject`
- `GET /faults`
- `POST /faults/restore`
- `POST /faults/restore-all`

The equivalent Python lifecycle is:

```python
from chaoslab import ChaosLabClient

chaos = ChaosLabClient()
chaos.inject("n_plus_one", service="checkout", severity="P1")
chaos.status()
chaos.restore("checkout")
chaos.restore_all()
```

Reinjecting the same fault/service replaces the active state and increments its generation. Restoring a non-active fault is safe and reports zero removals.

## Supported fault targets

| Fault | Supported target(s) | Primary observable effect |
| --- | --- | --- |
| `n_plus_one` | checkout | query count and latency rise while requests continue succeeding |
| `connection_leak` | checkout, inventory | simulated active connections grow until pool timeout/503 |
| `disk_exhaustion` | gateway, checkout, inventory, payment, worker | simulated disk usage grows until write failure/507 |
| `broken_config` | payment | payment authentication/configuration fails while unrelated services remain healthy |
| `memory_leak` | gateway, checkout, inventory, payment, worker | retained memory grows until a controlled simulated restart/503 |

Unsupported fault/service pairs are rejected rather than silently creating a no-op scenario.

## Severity semantics

Severity is monotonic:

- `P1` produces the strongest or earliest failure behavior;
- `P2` is intermediate;
- `P3` allows more progression before terminal failure.

For progressive disk, memory, and connection faults, higher severity reaches failure earlier. Unit tests lock this relationship in so benchmark difficulty cannot be accidentally inverted later.

## Manual diagnosis guide

Phase 2 is valid only if a human can infer each fault from legal observables rather than the hidden controller state.

### N+1 query

Expected evidence:

- healthy `/orders` performs one batched query;
- under the fault, `/orders` still succeeds but query count increases sharply;
- `chaoslab_db_queries_last_request` rises;
- request latency rises;
- a fatal application exception is not required.

### Connection leak

Expected evidence:

- early inventory/checkout requests succeed;
- `simulated_db_connections` grows monotonically;
- the effective capacity is eventually reached;
- requests then fail with connection-pool timeout/503;
- restore returns connection state to zero.

### Disk exhaustion

Expected evidence:

- simulated disk usage rises over successive requests;
- service health remains available while the fault progresses;
- requests eventually fail with simulated `no space left on device`/507;
- restore deletes bounded simulator files and returns usage to zero.

### Broken configuration

Expected evidence:

- payment succeeds before injection;
- payment fails with authentication/configuration rejection after injection;
- the gateway reports a payment dependency failure;
- unrelated inventory requests continue succeeding;
- restore returns both payment and gateway behavior to baseline.

### Memory leak

Expected evidence:

- retained simulated bytes grow across requests;
- the process eventually records a controlled restart event and fails the triggering request;
- retained bytes clear after that simulated restart;
- the restart counter remains visible as evidence;
- explicit restore returns subsequent requests to baseline.

## Restart semantics

ChaosLab distinguishes **scenario intent** from **ephemeral process artifacts**:

- active fault definitions live in Redis and intentionally survive a service-container restart;
- leaked connection counters, retained memory chunks, and temporary process-local artifacts do not survive restart;
- an explicit controller restore removes scenario intent and resets the target service.

The Phase 2 CI gate injects active memory- and connection-leak faults, proves process-local state is non-zero, restarts both services, proves that ephemeral state returned to zero, verifies the fault definitions still exist in Redis, and finally restores them explicitly.

## Reproducibility

Each injected fault records:

- fault type;
- service;
- severity;
- seed;
- fault-specific configuration;
- generation.

The same fault configuration and seed must preserve the same causal structure and deterministic thresholds. Later benchmark phases will version entire scenarios on top of these primitives.

## Load generator

`chaoslab.loadgen` supports:

- `normal`;
- `burst`;
- `sustained`.

The target base URL and path are configurable, so traffic can be directed at the gateway or a specific service. It records request count, errors, mean latency, and p95 latency. The cumulative CI gate executes the normal profile against the live gateway after fault restoration and requires zero request errors.

## Phase 2 validation

```bash
make chaoslab-test
make compose-validate
docker compose down -v --remove-orphans
docker compose up -d --build
python scripts/phase2-smoke.py
```

The complete Phase 2 gate also reruns every Phase 1 lint, typing, migration, integration, frontend-build, and clean-start requirement. Phase 2 is not complete until those prior guarantees and all ChaosLab tests pass together from a clean environment.
