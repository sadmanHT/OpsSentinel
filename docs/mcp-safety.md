# MCP Investigation Tooling and Safety Boundary

Phase 3 exposes evidence-gathering capability without exposing unrestricted infrastructure access or ChaosLab hidden ground truth.

## Legal tool surface

The backend publishes a typed logical MCP registry at:

- `GET /mcp/tools`
- `POST /mcp/invoke`
- `GET /mcp/health`

The registry contains:

- `search_logs`
- `query_metrics`
- `execute_sql`
- `list_deployments`
- `inspect_deployment`
- `inspect_commit`
- `inspect_git_diff`
- `search_code`
- `search_documentation`
- `run_diagnostic`

Every response is an evidence envelope. Tools return observations only; they do not return root-cause conclusions.

## Hidden-state boundary

The agent principal may observe `backend`, `gateway`, `checkout`, `inventory`, `payment`, and `worker`. It may not target the ChaosLab controller. The controller contains injected-fault intent and is test-harness/ground-truth infrastructure only.

## Risk policy

- R0: read-only evidence retrieval; automatic.
- R1: allowlisted diagnostics; automatic.
- R2: reversible action; requires a human approval identifier.
- R3: destructive action; blocked.

Phase 3 exposes only R0 and R1 tools.

## SQL safety

`execute_sql` accepts one statement and only the `SELECT`, `SHOW`, `EXPLAIN`, and `EXPLAIN ANALYZE SELECT` forms. Mutation, administrative SQL, row locks, multiple statements, `SELECT INTO`, and dangerous file/large-object functions are rejected before execution.

The runtime connection uses the `opssentinel_reader` PostgreSQL role created by migration `0002_mcp_readonly_role`. The role is non-superuser and defaults to read-only transactions. Production deployments should replace the local-development credential through normal secret provisioning.

## Diagnostic safety

No general shell endpoint exists. `run_diagnostic` maps an enum to fixed argument vectors and uses `subprocess.run(..., shell=False)`.

Allowlisted commands are:

- `df`
- `free`
- `ps`
- `curl` to an approved service and approved path only
- selected `backend/tests/...` pytest targets

Shell fragments, arbitrary executables, arbitrary URLs, and path traversal are rejected.

## Bounded results and timeouts

Registry calls share a hard execution timeout and serialized output cap. Individual tools also bound rows, log entries, search hits, paths, query length, and service targets.

## Git and documentation isolation

The backend container receives the project checkout at `/workspace` as a read-only bind mount. Git and documentation tools operate only inside that root. The agent never receives host shell or filesystem access.

## Manual incident diagnosis gate

`scripts/phase3-mcp-smoke.py` injects incidents using test-harness control, generates symptom traffic, and then gathers diagnostic evidence only through the legal MCP tool surface. The script covers all five Phase 2 incidents plus security-boundary negative cases.
