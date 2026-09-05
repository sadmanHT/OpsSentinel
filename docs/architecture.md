# OpsSentinel Architecture

## Mission

OpsSentinel is an experimental platform for studying when additional reasoning helps autonomous incident-response agents and when it creates failure modes such as anchoring, over-investigation, overconfidence, and false conclusions.

## Four systems

1. **ChaosLab** — reproducible incident simulator and fault-injection framework.
2. **Agent Runtime** — LangGraph investigator with constrained MCP tools.
3. **Benchmark & Evaluation Laboratory** — difficulty-stratified, adversarial, compound, temporal, and counterfactual evaluation.
4. **Research & Observability Layer** — traces, scores, calibration, efficiency, cost, safety, and failure analysis.

## Phase 1 boundaries

Phase 1 implements infrastructure and contracts only. It deliberately does **not** implement ChaosLab faults, MCP tools, LangGraph agent behavior, benchmark scenarios, or research experiments.

### Backend contract

- FastAPI provides the application boundary.
- Pydantic models define strict in-memory domain contracts.
- SQLAlchemy defines the persistence schema.
- Alembic owns schema evolution.
- PostgreSQL + pgvector is the long-lived relational/vector store.
- Redis is reserved for ephemeral/cache/runtime state in later phases.

### Model-provider boundary

Configuration includes `llm_provider` and `llm_model`, but Phase 1 does not call an LLM. Later code must depend on a provider abstraction so a local/open model remains a supported default.

## Evidence vs reasoning

Evidence is an observation from a source. A hypothesis is an interpretation. Later agent conclusions must cite evidence identifiers rather than treating model-generated reasoning as evidence.

## Reproducibility

Future experimental runs must record model identity/configuration, seed, prompt version, architecture version, scenario version, dataset split, tool budget, retrieval settings, timestamp, and evaluation version.
