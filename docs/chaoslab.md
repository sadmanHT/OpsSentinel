# ChaosLab

ChaosLab is OpsSentinel's reproducible production-incident simulator. It exists independently of the AI agent so incidents can be validated manually and used as controlled experimental inputs.

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

All service requests emit structured JSON logs and expose Prometheus-compatible `/metrics` plus a human-readable `/telemetry` snapshot. The `/telemetry` endpoint contains observations only; it does not identify the injected fault or ground-truth root cause.

## Safety of the simulator

ChaosLab deliberately produces production-like symptoms without destabilizing the host or CI runner:

- disk exhaustion writes only small, bounded files inside the service container;
- memory leaks retain a bounded buffer and trigger a controlled simulated restart event rather than intentionally OOM-killing the host;
- connection leaks use a bounded simulated pool counter rather than exhausting the real PostgreSQL server;
- all artifacts are reset on fault restoration or container replacement.

These constraints preserve diagnostic signals while keeping repeated experiments reproducible and safe.

## Controller API

Inject a fault:

```bash
curl -X POST http://localhost:8100/faults/inject \
  -H 'content-type: application/json' \
  -d '{"fault":"n_plus_one","service":"checkout","severity":"P1","seed":42}'
```

Restore a service:

```bash
curl -X POST http://localhost:8100/faults/restore \
  -H 'content-type: application/json' \
  -d '{"service":"checkout"}'
```

Restore all faults:

```bash
curl -X POST http://localhost:8100/faults/restore-all
```

The controller is an experimental harness boundary. Future OpsSentinel agents must not receive this interface as an investigation tool because it reveals fault-control state.

## Fault primitives

### `n_plus_one`

Target: checkout. Healthy `/orders` performs one joined query. Under the fault, each order and item triggers additional queries, increasing request latency and the `db_query_count_last_request` signal without requiring a fatal application exception.

### `connection_leak`

Target: inventory. Each request consumes a bounded simulated connection slot until the configured capacity is reached, after which the service returns pool-timeout symptoms. Restoration clears the simulated pool.

### `disk_exhaustion`

Target: worker. Requests create bounded debug-log files and eventually return HTTP 507 with rising simulated disk utilization.

### `broken_config`

Target: payment. A configuration/authentication failure causes charge attempts to return HTTP 401 while unrelated infrastructure remains healthy.

### `memory_leak`

Target: worker. Requests retain bounded memory chunks. Crossing a deterministic threshold records a simulated restart and returns HTTP 503; the buffer is cleared to keep the environment safe.

## Reproducibility

Each injected fault records:

- fault type;
- service;
- severity;
- seed;
- fault-specific configuration;
- generation.

The same fault configuration and seed must preserve the same causal structure and thresholds. Later benchmark phases will version entire scenarios on top of these primitives.

## Load generator

`chaoslab.loadgen` supports normal, burst, and sustained profiles and records request count, errors, mean latency, and p95 latency.

## Phase 2 validation

The cumulative gate runs `scripts/phase2-smoke.py` against a fresh Docker Compose environment. It proves every fault can be injected, produces the expected observable symptom, can be restored, and returns to a healthy baseline while all Phase 1 gates remain green.
