# EvaluationLab

Phase 7 adds the scientific measurement layer for saved OpsSentinel benchmark trajectories. EvaluationLab scores agent behavior automatically and reproducibly; it does not change BenchmarkLab ground truth or force preferred research outcomes.

## Package boundary

`evaluationlab/` is a standalone Python 3.11+ package. It consumes saved BenchmarkLab scenario metadata and `BenchmarkRunArtifact` trajectories rather than calling the agent directly.

Core modules:

- `models.py` — strict typed evaluation cases, metrics, safety observations, calibration bins, and failure classifications;
- `adapter.py` — deterministic conversion from saved BenchmarkLab trajectories into `EvaluationCase` inputs;
- `metrics.py` — root-cause, compound-cause, evidence, efficiency, calibration, and safety scoring primitives;
- `engine.py` — deterministic per-case and aggregate evaluation plus failure taxonomy;
- `counterfactual.py` — controlled-family causal consistency, sensitivity, and invariance scoring;
- `reporting.py` — deterministic SVG reliability diagrams;
- `persistence.py` — typed storage/readback through the canonical `evaluation_runs`, `evaluation_scores`, and `experiment_metadata` tables.

## Measurement semantics

### Root-cause and compound correctness

EvaluationLab records:

- primary root-cause accuracy;
- secondary-cause recall;
- multi-root-cause precision and recall;
- exact-match correctness.

A compound incident is not treated as entirely correct when only its primary cause is found.

### Evidence quality

Evidence is derived from persisted tool provenance, not free-form reasoning text. Metrics include:

- evidence precision;
- evidence recall;
- critical evidence recall;
- distractor selection rate.

### Investigation efficiency and marginal evidence utility

Saved tool calls are classified as discriminative, repeated, irrelevant, or misleading. EvaluationLab records:

- useful evidence per tool call;
- duplicate calls;
- irrelevant calls;
- failed calls;
- misleading calls;
- total tool calls;
- steps to the first non-rejected correct hypothesis when observable.

### Confidence calibration

Agent confidence is compared with correctness using:

- Brier score;
- expected calibration error (ECE);
- reliability bins;
- deterministic SVG reliability diagrams.

### Safety

EvaluationLab measures:

- unsafe action attempts;
- blocked destructive requests;
- unnecessary approval requests;
- incorrectly classified tool risk.

Safety and execution integrity may be CI gates. Diagnostic accuracy and calibration remain measured research outcomes rather than thresholds chosen to make the agent appear successful.

## Failure taxonomy

The typed Phase 7 vocabulary includes:

- `ANCHORING`;
- `PREMATURE_CONVERGENCE`;
- `OVER_INVESTIGATION`;
- `MISSED_EVIDENCE`;
- `DISTRACTOR_CAPTURE`;
- `TOOL_MISUSE`;
- `TOOL_FAILURE`;
- `UNSUPPORTED_ASSERTION`;
- `TEMPORAL_REASONING_FAILURE`;
- `COMPOUND_CAUSE_OMISSION`;
- `BUDGET_EXHAUSTION`;
- `OVERCONFIDENCE`.

Every incorrect diagnosis receives at least one deterministic classification. `ANCHORING` is intentionally not inferred from distractor capture alone: the current saved trajectory contract does not expose a trustworthy signal that proves an early hypothesis persisted despite contradictory evidence. Phase 8 may add a stronger observable for that category; Phase 7 does not fabricate it from weaker proxies.

## Counterfactual evaluation

The controlled BenchmarkLab family `deploy-cron-latency` contains four variants:

1. `original`;
2. `gap_then_cron`;
3. `no_deploy_cron`;
4. `deploy_cron_disabled` — a fault-free `no_fault` control.

EvaluationLab scores all pairwise relationships and reports:

- **consistency** — whether prediction-change behavior matches expected causal-change behavior;
- **causal sensitivity** — whether predictions change when expected causes change;
- **causal invariance** — whether predictions remain stable when expected causes remain equivalent.

These metrics are deliberately separate from ordinary RCA correctness. For example, a no-fault control can be diagnosed incorrectly while still contributing to a causally consistent family response if the prediction changes appropriately relative to the faulted variants.

Family metrics are persisted as ordinary evaluation score rows under the synthetic scenario scope `counterfactual:<family>`, with `agent_run_id = NULL`; each individual variant remains a separate evaluation run linked to its real agent-run UUID.

## Persistence and reproducibility

Phase 7 reuses the canonical evaluation tables already present in the backend schema; no new Phase 7 migration is required.

Each persisted run records the dataset version, architecture version, model identity, seed, configuration, experiment metadata, metric rows, failure categories, and saved trace. Integration tests dispose and reopen the SQLAlchemy engine and require exact typed readback.

The same saved trajectory evaluated twice must produce the same score object.

## Validation

Static and known-answer checks:

```bash
python -m pip install -e 'evaluationlab[dev]'
ruff check evaluationlab scripts/phase7-evaluation-smoke.py \
  scripts/phase7-representative-evaluation-smoke.py \
  scripts/phase7-counterfactual-evaluation-smoke.py
mypy evaluationlab/evaluationlab
pytest evaluationlab/tests
```

PostgreSQL persistence/restart check after backend migrations:

```bash
pytest evaluationlab/integration/test_postgres_persistence.py
```

The clean-state Compose gate additionally runs:

```bash
python scripts/phase7-evaluation-smoke.py
python scripts/phase7-representative-evaluation-smoke.py
python scripts/phase7-counterfactual-evaluation-smoke.py
```

Generated CI research artifacts under `artifacts/phase7/` include:

- `representative-evaluation-summary.json`;
- `representative-reliability.svg`;
- `counterfactual-evaluation-summary.json`.

These artifacts report measured results. They are not pass/fail scorecards for preferred research hypotheses.
