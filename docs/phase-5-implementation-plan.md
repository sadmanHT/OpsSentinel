# Phase 5 Implementation Plan — Safety, Human Approval, Verification, and Fault Recovery

## Status

**Implemented and cumulatively validated on the Phase 5 closeout branch.** The authoritative closeout record is `docs/phase-5-handoff.md`. Phase 6 may rely on Phase 5 only after the closeout PR is merged and the same Phase 1–5 gate passes on `main`.

This plan is retained as the historical implementation specification for Phase 5.

## Objective

Move OpsSentinel from an evidence-grounded investigating agent to a controlled operational agent without weakening the Phase 3 MCP safety boundary or the Phase 4 evidence/persistence guarantees.

## Required implementation

1. **Human approval interrupts for R2 actions**
   - Persist the proposed action and approval request.
   - Pause the run before execution.
   - Resume only after explicit approval or rejection.
   - Support abandoned approval without corrupting state.

2. **Typed approval request context**
   - action
   - rationale
   - evidence IDs
   - expected benefit
   - possible risk
   - rollback strategy
   - approval identifier and decision metadata

3. **Deterministic verification tools**
   - run tests
   - reproduce a request
   - rerun a load test
   - EXPLAIN ANALYZE through the existing read-only SQL boundary
   - restart a sandbox service
   - rollback a sandbox deployment

4. **Risk enforcement**
   - R0: automatic
   - R1: automatic diagnostic
   - R2: requires a trusted approval ID
   - R3: always blocked
   - no raw shell, Docker socket, unrestricted container control, or hidden ChaosLab ground truth is exposed to the agent

5. **Tool-failure recovery**
   - timeout
   - 503/unavailable dependency
   - malformed result
   - partial metrics
   - unavailable logs
   - bounded retry count with backoff
   - alternate-tool or reduced-confidence continuation where appropriate
   - graceful termination instead of crashes

6. **Diminishing-return protection**
   - detect repeated non-progressing calls
   - record redundant/failed calls in the trajectory
   - encourage verification, alternative hypotheses, or conclusion after sustained non-progress

## Testing contract

Phase 5 is not complete on feature tests alone. Required validation is cumulative:

- Phase 1 schemas/config/migrations/backend/frontend/Docker/CI regression
- Phase 2 ChaosLab baseline/fault/restoration/determinism regression
- Phase 3 MCP contracts, SQL/command/path/service isolation, and R0-R3 policy regression
- Phase 4 graph, evidence grounding, persistence, budgets, termination, and five-fault agent regression
- Phase 5 approval, rejection, abandoned approval, persisted resume, action verification, retry/failure recovery, and zero executed R3 operations

The complete five-incident set must be exercised under normal tools, transient failures, approved actions, and rejected actions.

## Clean-state exit gate

Before merge:

1. `docker compose down -v --remove-orphans`
2. clean build/start
3. migrations from zero
4. all backend/ChaosLab/frontend tests
5. all accumulated integration/security/failure-path suites
6. Phase 2, Phase 3, Phase 4, and Phase 5 smoke flows
7. restart/resume persistence checks
8. log inspection for hidden tracebacks/critical failures
9. persisted-record cross-checks
10. CI-equivalent checks
11. fix any failure and rerun the relevant chain

## Validation outcome

The Phase 5 closeout branch passed the complete pre-merge cumulative gate in CI run #75, including backend Ruff/mypy/unit/integration/migration checks, ChaosLab, frontend production build, the clean-state Compose Phase 1–5 integration gate, restart cleanup, and teardown. See `docs/phase-5-handoff.md` for the exact validation record and remaining post-merge boundary.

## Phase 6 boundary

Only after Phase 5 closeout is merged and the push-triggered `main` CI is green may Phase 6 BenchmarkLab rely on Phase 5 behavior. Phase 6 may assume only the guarantees recorded in `docs/phase-5-handoff.md`.
