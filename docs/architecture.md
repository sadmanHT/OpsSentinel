# OpsSentinel Architecture

## Mission

OpsSentinel is an experimental platform for studying when additional reasoning helps autonomous incident-response agents and when it creates failure modes such as anchoring, over-investigation, overconfidence, and false conclusions.

## Four systems

1. **ChaosLab** — reproducible incident simulator and fault-injection framework.
2. **Agent Runtime** — LangGraph investigator with constrained MCP tools.
3. **Benchmark & Evaluation Laboratory** — difficulty-stratified, adversarial, compound, temporal, and counterfactual evaluation.
4. **Research & Observability Layer** — traces, scores, calibration, efficiency, cost, safety, causal reasoning, and failure analysis.

## Implemented system through Phase 7

### Foundation and persistence

- FastAPI provides the backend application boundary.
- Pydantic models define strict typed contracts.
- SQLAlchemy defines persistence mappings and Alembic owns schema evolution.
- PostgreSQL + pgvector is the long-lived relational/vector store.
- Redis provides ephemeral/runtime state where required.
- The canonical schema includes incidents, evidence, hypotheses, diagnoses, agent runs/checkpoints, evaluation runs, evaluation scores, and experiment metadata.

### ChaosLab

ChaosLab provides deterministic synthetic services, modular fault injection, telemetry, and restoration. The controller is a test-harness boundary and is never exposed as an agent tool.

### MCP safety boundary

The agent investigates through a constrained MCP registry. Tool contracts, SQL restrictions, command/path/service isolation, and R0–R3 risk classification prevent unrestricted infrastructure access.

### Agent Runtime

The LangGraph agent maintains typed incident, evidence, hypothesis, plan, tool-call, diagnosis, action, approval, verification, retry, and checkpoint state. Phase 5 adds approval, post-action verification, bounded recovery, and persisted resume semantics.

### BenchmarkLab

BenchmarkLab owns evaluator-visible scenario truth and reproducible incident launch. Its v1 catalog contains 50 structurally varied scenarios across Easy, Medium, Hard, Adversarial, and Compound tiers, with explicit temporal structure, controlled counterfactual variants, structural holdouts, fixed seeds, and public-only agent payloads.

Benchmark launch is independent of agent execution. `BenchmarkRunner.run()` can also launch the real agent and produce a saved `BenchmarkRunArtifact` while restoring ChaosLab in `finally`.

### EvaluationLab

EvaluationLab consumes saved benchmark trajectories and automatically computes:

- root-cause and compound-cause correctness;
- evidence precision/recall, critical evidence recall, and distractor selection;
- investigation efficiency and marginal evidence utility;
- Brier score, expected calibration error, reliability bins, and reliability diagrams;
- safety metrics;
- deterministic failure classifications;
- counterfactual consistency, causal sensitivity, and causal invariance.

Each run records reproducibility metadata and can persist metric rows, traces, experiment configuration, and failure categories through the canonical evaluation tables. PostgreSQL integration tests require exact typed readback after engine restart.

Counterfactual family metrics are stored separately from ordinary RCA correctness so causal response behavior is not mistaken for diagnosis accuracy.

## End-to-end research data flow

1. BenchmarkLab selects a typed scenario and restores ChaosLab to baseline.
2. ChaosLab injects deterministic faults and stimuli independently of the agent.
3. Only the public incident contract crosses into the agent API.
4. The agent investigates through constrained MCP tools and persists its trajectory.
5. BenchmarkLab records a `BenchmarkRunArtifact` containing the saved trajectory plus evaluator-only expected labels.
6. EvaluationLab deterministically adapts the saved trajectory into an `EvaluationCase`.
7. EvaluationLab computes per-run metrics, failure classifications, calibration data, and optional counterfactual family metrics.
8. Scores, traces, experiment configuration, versions, seeds, and model/architecture identity are persisted for later research comparison.
9. CI can export JSON/SVG research artifacts without turning observed accuracy or calibration values into preferred-result thresholds.

## Evidence vs reasoning

Evidence is an observation from a source. A hypothesis is an interpretation. Agent conclusions cite evidence identifiers rather than treating model-generated reasoning as evidence. EvaluationLab likewise derives benchmark evidence tags from persisted tool provenance rather than scoring free-form reasoning text as evidence.

## Ground-truth boundary

Benchmark ground truth is evaluator-only. Difficulty, split, injected faults, expected RCA labels, and counterfactual truth are excluded from the agent-visible request. Evaluation begins only from saved trajectories after agent execution.

## Provider boundary

Agent configuration depends on a provider abstraction. Local/open-model execution remains supported and paid APIs are not required. Evaluation metadata records the provider/model identity used by the experiment rather than fabricating a deterministic label for live Compose runs.

## Reproducibility

Experimental runs record, as applicable, model identity/configuration, seed, prompt/architecture version, scenario version, dataset version/split, tool budget, retrieval settings, timestamp, and evaluation version.

The same saved trajectory must evaluate deterministically. Clean-state CI rebuilds the environment, applies migrations, executes the accumulated Phase 1–7 validation chain, checks persisted state and logs, exercises restart cleanup, and tears down disposable state.

See `docs/chaoslab.md`, `docs/mcp-safety.md`, `docs/evaluationlab.md`, `docs/research-hypotheses.md`, and the phase handoff records for implementation-specific guarantees.
