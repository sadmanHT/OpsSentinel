# Phase 5 Handoff — Safety, Human Approval, Verification, and Fault Recovery

## Status

Phase 5 implementation and the complete pre-merge Phase 1–5 cumulative validation gate have passed on `phase-5-closeout`. Merge to `main` and post-merge `main` revalidation remain required before Phase 6 may rely on this handoff as final.

## Implementation summary

Phase 5 moves OpsSentinel from an evidence-grounded investigator to a controlled operational agent while preserving the Phase 3 MCP safety boundary and Phase 4 evidence/persistence guarantees.

Implemented behavior includes:

- typed human-approval requests for R2 actions, including rationale, supporting evidence, expected benefit, risk, rollback strategy, approval identity, and decision metadata;
- persisted pause/resume behavior for approved, rejected, and abandoned approvals;
- deterministic verification/remediation tools including test execution, request reproduction, load-test reruns, EXPLAIN ANALYZE, sandbox-service restart, and sandbox-deployment rollback;
- R0/R1 automatic execution, R2 approval enforcement, and unconditional R3 blocking;
- bounded retry handling with backoff and retry trajectory capture;
- graceful conversion of malformed tool results and unexpected handler exceptions into bounded failure responses instead of agent crashes;
- timeout, 503/unavailable dependency, partial-metric, and unavailable-observability recovery paths;
- diminishing-return protection for repeated non-progressing investigation;
- post-action verification so remediation success is established from simulator state rather than assumed from action completion;
- cumulative persistence checks for checkpoints and diagnoses.

## Closeout coverage added in PR #7

The closeout branch adds the literal Phase 5 specification coverage that was missing from the original Phase 5 merge:

- five-incident rejected-action live matrix;
- five-incident transient-recovery runtime matrix;
- retry/unavailability coverage across all 16 major MCP tools;
- explicit timeout recovery coverage;
- malformed-result handling;
- unexpected handler-exception handling;
- partial-metric handling;
- hardened `RetryingToolRegistry` behavior for malformed/unexpected MCP failures;
- stricter clean-state Compose persistence thresholds.

## Important design decisions

1. **MCP remains the authority for safety.** Retry behavior decorates the existing registry; it does not bypass permissions or R0–R3 policy.
2. **R2 approval is explicit and trusted.** Operational actions cannot execute merely because the model recommends them.
3. **R3 remains non-executable.** Phase 5 may recommend an R3 action, but no prohibited R3 operation is allowed to execute.
4. **Failures are trajectory evidence.** Retryable failures, terminal tool failures, and degraded observability are recorded rather than silently discarded.
5. **Malformed/unexpected tool behavior is bounded.** Integration defects are converted to typed failed tool responses so the runtime can terminate or continue safely rather than crash.
6. **Verification is independent of action completion.** Remediation is considered successful only when deterministic post-action checks reflect the expected simulator state.
7. **Cumulative validation is mandatory.** Phase 5 is not accepted on isolated feature tests; Phases 1–5 must work together from a clean environment.

## Migrations and configuration

No new Phase 5 closeout database migration was required by PR #7. Existing Phase 5 persistence schema and configuration remain authoritative.

CI clean-state validation continues to apply migrations from zero and verifies rollback/re-upgrade behavior.

## Validation commands and gates

The repository CI-equivalent gate validates the same required chain described in the Phase 5 specification, including:

```bash
ruff check .
mypy app
pytest
alembic upgrade head
pytest <integration suites>
alembic downgrade <previous> && alembic upgrade head
docker compose down -v --remove-orphans
docker compose build
docker compose up -d
python scripts/phase2-smoke.py
python scripts/phase3-mcp-smoke.py
python scripts/phase4-agent-smoke.py
python scripts/phase5-operational-smoke.py
python scripts/phase5-approval-negative-smoke.py
python scripts/phase5-rejected-matrix-smoke.py
```

The Compose gate additionally checks persistence counts, restart cleanup, service logs, and clean teardown.

## Pre-merge validation results

CI run **#75** on closeout head `1ec73afd393446c1950b9288205d9aa7c0f80646` passed all four jobs:

- **backend: PASS** — Ruff, strict mypy, unit tests, backend/MCP/agent startup smoke, migration upgrade, integration tests, migration rollback and re-upgrade, and container cleanup;
- **chaoslab: PASS** — Ruff, unit tests, and import smoke tests;
- **frontend: PASS** — production build;
- **compose: PASS** — Compose-file validation, image build, clean-state cumulative Phase 1–5 integration gate, restart cleanup regression, and clean teardown.

The clean-state cumulative gate includes the accumulated Phase 2, Phase 3, Phase 4, and Phase 5 smoke flows and the Phase 5 rejected-action matrix.

## Phase 5 required behavior demonstrated

- approval: approve, reject, abandoned approval, persisted resume;
- safety: R0 executes, R1 executes, R2 pauses until trusted approval, R3 blocked;
- recovery: injected failures across every major MCP tool do not crash the runtime;
- verification: post-remediation measurements reflect simulator state;
- scenario matrix: the five core incidents are covered under normal tools, transient failures, approved actions, and rejected actions;
- zero prohibited R3 operations execute.

## Known non-blocking limitations

- The deterministic provider and simulator are research fixtures, not a claim that all real production incidents will be diagnosed correctly.
- Phase 5 validates bounded failure recovery and safety behavior; BenchmarkLab in Phase 6 is responsible for broader difficulty, adversarial, temporal, compound, and hidden-test evaluation.
- Paid external LLM APIs are not required for the Phase 5 gate.

## Exact Phase 6 prerequisites

Phase 6 may rely on the following only after PR #7 is merged and the same cumulative gate is green on `main`:

- stable typed incident/evidence/hypothesis/action/approval/checkpoint contracts;
- constrained MCP tool access and R0–R3 safety enforcement;
- persisted Phase 4/5 agent runs and pause/resume state;
- deterministic verification tools;
- bounded retry/failure handling without runtime crashes;
- approved/rejected R2 execution semantics;
- post-action verification;
- clean-state reproducibility of the complete Phase 1–5 system.

## Final closeout condition

Do not treat this handoff as final until PR #7 is merged and post-merge `main` CI passes the complete Phase 1–5 gate. At that point Phase 5 is fully closed and Phase 6 may consume these guarantees.
