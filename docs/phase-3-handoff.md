# Phase 3 Handoff Record

## Status

**Complete. The cumulative Phase 1 + Phase 2 + Phase 3 CI gate is green.**

Validation completed on the Phase 3 branch with CI run #37 (`34012483216`). Backend lint, strict typing, unit tests, startup/MCP smoke tests, migrations, integration tests, rollback/re-upgrade, frontend production build, ChaosLab tests, and the clean-state Compose cumulative gate all passed. The Compose gate also passed the Phase 2 regression scenarios, the Phase 3 MCP-only five-incident diagnosis harness, restart cleanup regression, log cleanliness checks, and clean teardown.

## Intended outcome

Phase 3 adds a controlled investigation boundary for future agents. The legal surface provides bounded logs, metrics, read-only SQL, Git/deployment inspection, documentation search, and allowlisted diagnostics while excluding ChaosLab hidden fault-control state.

## Security boundary

- Future agents do not receive container shell, host shell, Docker socket, PostgreSQL owner credentials, Redis scenario-control access, or the ChaosLab controller.
- `opssentinel_reader` is the restricted database identity for investigation SQL.
- SQL mutation and administrative statements are blocked in policy before execution and again by database transaction/role restrictions.
- Diagnostics use explicit command templates with `shell=False`.
- Repository and documentation paths are confined to read-only approved roots.
- Services are allowlisted; `controller` is intentionally not a legal target.
- R0/R1 are automatic, R2 requires human approval, and R3 is blocked.

## Completed cumulative gate

1. Phase 1 backend lint/type/unit/migration/integration checks pass.
2. Frontend production build passes.
3. Phase 2 ChaosLab unit tests and all five live fault/restoration scenarios pass.
4. Every Phase 3 tool has valid, invalid, timeout/unavailable, bounded-output, and permission coverage through the shared registry contract plus tool-specific tests.
5. Mutation SQL, shell escapes, arbitrary executable commands, path traversal, and unauthorized service interaction are rejected.
6. All five existing incidents can be diagnosed with evidence gathered only through legal MCP tools.
7. Clean-state Compose build/start/migration/security/evidence workflows pass without hidden tracebacks or stale state.
8. CI-equivalent validation is green.

## Next-phase boundary

Phase 4 may rely only on this tested tool registry and safety policy. It must not bypass the MCP boundary or consume ChaosLab controller state.
