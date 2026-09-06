# Phase 4 Handoff Record

## Status

**Complete on the Phase 4 branch. The cumulative Phase 1 + Phase 2 + Phase 3 + Phase 4 gate is green.**

Primary clean-state validation completed on CI run #52 (`34022420732`). Backend lint, strict typing, unit tests, startup/import smoke checks, migration upgrade, PostgreSQL integration tests, migration rollback/re-upgrade, frontend production build, ChaosLab tests, and the clean-state Compose cumulative gate all passed. The Compose gate also passed the Phase 2 smoke scenarios, the Phase 3 MCP-only five-incident harness, the Phase 4 five-fault autonomous-agent harness, persisted checkpoint/diagnosis checks, restart cleanup regression, critical-log scans, and clean teardown.

## Intended outcome

Phase 4 adds the first evidence-grounded autonomous incident investigator while intentionally keeping the architecture single-agent and recommendation-only.

The runtime executes a LangGraph workflow:

`START -> TRIAGE -> PLAN -> SELECT TOOL -> EXECUTE TOOL -> STORE EVIDENCE -> UPDATE HYPOTHESIS -> ENOUGH EVIDENCE? -> DIAGNOSE -> RECOMMEND -> REPORT -> END`

It uses only the Phase 3 MCP registry and safety boundary for investigation. It does not bypass MCP, consume ChaosLab hidden fault-control state, or execute production remediation.

## Important design decisions

- Single-agent LangGraph runtime; no multi-agent coordination in Phase 4.
- Typed state tracks the incident, plan, evidence, hypotheses, tool history, current hypothesis, confidence, budgets, proposed action, verification state, and final diagnosis.
- Evidence remains separate from interpretation. Final factual claims are grounded in persisted evidence IDs.
- The agent is bounded by configurable step, tool-call, repeated-identical-call, wall-clock, token, and cost budgets and terminates gracefully on exhaustion.
- Durable SQL checkpoints persist run state and support pause/resume semantics.
- The default provider remains `local`; CI uses an explicit deterministic provider so paid APIs are not required for validation.
- A deterministic reasoning provider supplies reproducible offline/CI behavior. Optional local-model support remains behind the provider abstraction.
- Phase 4 stops at recommendation/reporting. Human approval, action execution, verification, and recovery remain Phase 5 concerns.

## Persistence and migration changes

- Added Alembic migration `0003_agent_checkpoints.py`.
- Added the `agent_checkpoints` table for durable serialized agent state and checkpoint revision tracking.
- Agent runs persist evidence, hypotheses, tool history, diagnoses, and checkpoint state in PostgreSQL.
- The cumulative Compose gate verifies that both `incidents` and `agent_checkpoints` exist from a zero-state migration path.

## Configuration changes

Phase 4 adds or relies on these agent settings:

- `OPSSENTINEL_LLM_PROVIDER` (application default: `local`; CI: `deterministic`)
- `OPSSENTINEL_LLM_MODEL`
- `OPSSENTINEL_LLM_TIMEOUT_SECONDS`
- `OPSSENTINEL_LOCAL_MODEL_BASE_URL`
- `OPSSENTINEL_MAX_STEPS`
- `OPSSENTINEL_MAX_TOOL_CALLS`
- `OPSSENTINEL_MAX_REPEATED_IDENTICAL_CALLS`
- `OPSSENTINEL_AGENT_TIME_LIMIT_SECONDS`
- `OPSSENTINEL_AGENT_TOKEN_BUDGET`
- `OPSSENTINEL_AGENT_COST_BUDGET`

The CI environment explicitly sets `OPSSENTINEL_LLM_PROVIDER=deterministic` while the default-provider unit test removes that environment override before verifying the product default remains `local`.

## Validation commands and results

The normal CI workflow on run #52 (`34022420732`) passed all jobs.

### Backend

```bash
python -m pip install -e 'backend[dev]'
ruff check backend
mypy backend/app
pytest backend/tests -m 'not integration'
```

Startup/import checks passed for the FastAPI app, MCP registry, and `AgentRuntime.architecture_version == 'phase4-single-agent-v1'`.

Database validation passed:

```bash
cd backend
alembic upgrade head
pytest tests -m integration
alembic downgrade base
alembic upgrade head
```

### ChaosLab

```bash
python -m pip install -e 'chaoslab[dev]'
ruff check chaoslab
pytest chaoslab/tests
```

ChaosLab import smoke tests also passed.

### Frontend

```bash
cd frontend
npm install --no-audit --no-fund
npm run build
```

The production build passed.

### Clean-state cumulative Compose gate

The CI job validated Compose configuration, rebuilt images, removed prior state, started the full stack, waited for backend/MCP/agent/simulator health, then ran:

```bash
python scripts/phase2-smoke.py
python scripts/phase3-mcp-smoke.py
python scripts/phase4-agent-smoke.py
```

The Phase 4 smoke runner completed all five existing injected faults through `/agent`:

- N+1 query regression
- connection leak / pool exhaustion
- disk exhaustion
- broken payment configuration
- memory leak

The gate additionally verified at least five persisted `agent_checkpoints` and diagnoses, normal healthy load after restoration, required metrics/tool surfaces, the `phase4-single-agent-v1` agent health marker, absence of `Traceback`, `Unhandled exception`, or `CRITICAL` output in inspected service logs, restart cleanup behavior, and clean teardown.

## Phase 4 behavior guaranteed by tests

1. The agent uses only legal MCP tools from the Phase 3 registry.
2. Evidence is recorded and survives persistence.
3. Hypotheses and tool history persist with the run.
4. Final diagnoses are structured and evidence-grounded.
5. Pause/resume works across durable checkpoints.
6. Tool/step/repetition budgets prevent unbounded investigation loops and fail gracefully when exhausted.
7. The runtime terminates and does not crash across all five current Phase 2 fault scenarios.
8. The flagship deployment-related N+1 incident is diagnosed end-to-end from a clean environment.
9. Phase 1 foundation, Phase 2 ChaosLab, and Phase 3 MCP/security regressions remain green.
10. The Phase 3 tool sandbox is not weakened by the agent runtime.

## Known non-blocking limitations

- The deterministic CI provider is intentionally heuristic and exists for reproducible engineering validation; it is not a research claim about model intelligence.
- Phase 4 does not target perfect incident-diagnosis accuracy and does not yet provide benchmark-scale accuracy/calibration experiments.
- Remediation is recommendation-only. The agent does not autonomously execute R2/R3 actions in this phase.
- Human approval workflows, deterministic post-action verification, rollback/recovery logic, and fault-recovery evaluation are intentionally deferred to Phase 5.
- Local-model quality, latency, and resource requirements are provider/model dependent and are not benchmarked in this phase.

## Next-phase boundary

Phase 5 may rely on the following tested guarantees only:

- A single autonomous LangGraph investigator can triage, plan, gather evidence through legal MCP tools, update hypotheses, diagnose, recommend, and report.
- Agent state and evidence are durable in PostgreSQL and can be resumed after interruption.
- Structured diagnoses cite evidence IDs.
- Budgets and repeated-call protection bound investigation.
- The Phase 3 MCP safety boundary remains authoritative and must not be bypassed.
- The current agent proposes actions but does not execute them.

Phase 5 should add safety-aware action execution, human approval, verification, and fault recovery on top of these guarantees without weakening the cumulative Phase 1-4 gate.
