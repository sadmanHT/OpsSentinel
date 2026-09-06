# Phase 5 Implementation Plan — Safety, Human Approval, Verification, and Fault Recovery

## Status

**In progress. Phase 6 is blocked until this phase passes its cumulative gate and is revalidated on `main`.**

This branch starts from the completed Phase 4 commit. It exists because the repository had no Phase 5 implementation branch or merged Phase 5 PR when Phase 6 was requested.

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

## Phase 6 boundary

Only after this phase is merged and the push-triggered `main` CI is green may a Phase 6 BenchmarkLab implementation branch be created. Phase 6 may rely only on Phase 5 behavior proven by that cumulative gate.
