import asyncio
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row

from app.config import Settings
from app.mcp.errors import (
    InvalidToolArguments,
    ServiceUnavailable,
    ToolTimeout,
    UnsafeOperation,
)
from app.mcp.models import (
    DiagnosticCommand,
    EvidenceEnvelope,
    ExecuteSqlArgs,
    InspectCommitArgs,
    InspectDeploymentArgs,
    InspectGitDiffArgs,
    PermissionSet,
    QueryMetricsArgs,
    RunDiagnosticArgs,
    SearchCodeArgs,
    SearchDocumentationArgs,
    SearchLogsArgs,
)
from app.mcp.policy import authorize_service
from app.mcp.registry_support import EmptyArgs
from app.mcp.safety import safe_relative_path, validate_git_ref, validate_readonly_sql
from app.mcp.services import ServiceClient, service_targets
from app.models.domain import EvidenceType


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


class InvestigationTools:
    def __init__(
        self,
        settings: Settings,
        permissions: PermissionSet,
        service_client: ServiceClient | None = None,
        command_runner: Callable[[list[str], Path | None, float], str] | None = None,
    ) -> None:
        if not isinstance(permissions, PermissionSet):
            raise TypeError("permissions must be a PermissionSet")
        self.settings = settings
        self.permissions = permissions
        self.services = service_client or ServiceClient(settings, permissions)
        self.command_runner = command_runner or self._run_command

    def _bounded_text(self, output: str) -> tuple[str, bool]:
        limit = max(1_000, min(32_000, self.settings.mcp_max_output_bytes // 2))
        if len(output) <= limit:
            return output, False
        return output[:limit], True

    async def search_logs(self, args: SearchLogsArgs) -> EvidenceEnvelope:
        authorize_service(self.permissions, args.service)
        params: dict[str, str | int] = {"limit": args.limit}
        if args.query:
            params["query"] = args.query
        if args.level:
            params["level"] = args.level
        if args.start_time:
            params["start_time"] = args.start_time.isoformat()
        if args.end_time:
            params["end_time"] = args.end_time.isoformat()
        payload = await self.services.get_json(args.service, "/observability/logs", params)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.LOG,
            source="mcp.search_logs",
            service=args.service,
            payload=payload,
        )

    async def query_metrics(self, args: QueryMetricsArgs) -> EvidenceEnvelope:
        authorize_service(self.permissions, args.service)
        params: dict[str, str | int] = {
            "metric": args.metric.value,
            "aggregation": args.aggregation.value,
        }
        if args.start_time:
            params["start_time"] = args.start_time.isoformat()
        if args.end_time:
            params["end_time"] = args.end_time.isoformat()
        payload = await self.services.get_json(args.service, "/observability/metrics", params)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.METRIC,
            source="mcp.query_metrics",
            service=args.service,
            payload=payload,
        )

    async def list_deployments(self, _args: EmptyArgs) -> EvidenceEnvelope:
        targets = service_targets(self.settings)
        deployments: list[dict[str, object]] = []
        for service in sorted(self.permissions.allowed_services):
            target = targets.get(service)
            if target is None:
                continue
            try:
                health = await self.services.get_json(service, "/health")
                status = "healthy"
            except (ServiceUnavailable, ToolTimeout):
                health = None
                status = "unavailable"
            deployments.append(
                {
                    "service": service,
                    "deployment": target.deployment,
                    "status": status,
                    "health": health,
                }
            )
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DEPLOYMENT,
            source="mcp.list_deployments",
            payload=deployments,
        )

    async def inspect_deployment(self, args: InspectDeploymentArgs) -> EvidenceEnvelope:
        authorize_service(self.permissions, args.service)
        target = self.services.target(args.service)
        health = await self.services.get_json(args.service, "/health")
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DEPLOYMENT,
            source="mcp.inspect_deployment",
            service=args.service,
            payload={
                "service": args.service,
                "deployment": target.deployment,
                "health": health,
            },
        )

    async def execute_sql(self, args: ExecuteSqlArgs) -> EvidenceEnvelope:
        query = validate_readonly_sql(args.query)
        payload = await asyncio.to_thread(self._execute_sql_sync, query, args.max_rows)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DATABASE,
            source="mcp.execute_sql",
            payload=payload,
            truncated=bool(payload["truncated"]),
        )

    def _execute_sql_sync(self, query: str, max_rows: int) -> dict[str, object]:
        timeout_ms = max(100, int(self.settings.mcp_tool_timeout_seconds * 1000))
        try:
            with psycopg.connect(
                self.settings.mcp_database_url,
                connect_timeout=max(1, int(self.settings.mcp_tool_timeout_seconds)),
                row_factory=tuple_row,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(f"SET LOCAL statement_timeout = '{timeout_ms}ms'")
                    cur.execute(query)
                    if cur.description is None:
                        columns: list[str] = []
                        rows: list[tuple[object, ...]] = []
                    else:
                        columns = [column.name for column in cur.description]
                        rows = list(cur.fetchmany(max_rows + 1))
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            return {
                "columns": columns,
                "rows": [_json_safe(row) for row in rows],
                "row_count": len(rows),
                "truncated": truncated,
            }
        except psycopg.errors.QueryCanceled as exc:
            raise ToolTimeout("database statement timed out") from exc
        except psycopg.Error as exc:
            raise ServiceUnavailable("read-only database is unavailable") from exc

    async def inspect_commit(self, args: InspectCommitArgs) -> EvidenceEnvelope:
        revision = validate_git_ref(args.revision)
        output = await asyncio.to_thread(
            self.command_runner,
            [
                "git",
                "-C",
                str(self.settings.mcp_repo_root),
                "show",
                "--no-ext-diff",
                "--no-color",
                "--format=fuller",
                "--stat",
                "--patch",
                revision,
            ],
            self.settings.mcp_repo_root,
            self.settings.mcp_tool_timeout_seconds,
        )
        output, truncated = self._bounded_text(output)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.CODE,
            source="mcp.inspect_commit",
            payload={"revision": revision, "output": output},
            truncated=truncated,
        )

    async def inspect_git_diff(self, args: InspectGitDiffArgs) -> EvidenceEnvelope:
        base = validate_git_ref(args.base)
        head = validate_git_ref(args.head)
        output = await asyncio.to_thread(
            self.command_runner,
            [
                "git",
                "-C",
                str(self.settings.mcp_repo_root),
                "diff",
                "--no-ext-diff",
                "--no-color",
                f"{base}..{head}",
            ],
            self.settings.mcp_repo_root,
            self.settings.mcp_tool_timeout_seconds,
        )
        output, truncated = self._bounded_text(output)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.CODE,
            source="mcp.inspect_git_diff",
            payload={"base": base, "head": head, "output": output},
            truncated=truncated,
        )

    async def search_code(self, args: SearchCodeArgs) -> EvidenceEnvelope:
        root = safe_relative_path(self.settings.mcp_repo_root, args.path)
        results = await asyncio.to_thread(self._search_text, root, args.query, args.limit)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.CODE,
            source="mcp.search_code",
            payload=results,
        )

    async def search_documentation(self, args: SearchDocumentationArgs) -> EvidenceEnvelope:
        root = safe_relative_path(self.settings.mcp_docs_root, args.path)
        results = await asyncio.to_thread(self._search_text, root, args.query, args.limit)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DOCUMENTATION,
            source="mcp.search_documentation",
            payload=results,
        )

    async def run_diagnostic(self, args: RunDiagnosticArgs) -> EvidenceEnvelope:
        command = self._diagnostic_command(args)
        output = await asyncio.to_thread(
            self.command_runner,
            command,
            self.settings.mcp_repo_root,
            self.settings.mcp_diagnostic_timeout_seconds,
        )
        output, truncated = self._bounded_text(output)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source="mcp.run_diagnostic",
            service=args.service,
            payload={"command": args.command.value, "output": output},
            truncated=truncated,
        )

    def _diagnostic_command(self, args: RunDiagnosticArgs) -> list[str]:
        if args.command == DiagnosticCommand.DF:
            if any((args.service, args.path, args.test)):
                raise InvalidToolArguments("df accepts no arguments")
            return ["df", "-h", "/"]
        if args.command == DiagnosticCommand.FREE:
            if any((args.service, args.path, args.test)):
                raise InvalidToolArguments("free accepts no arguments")
            return ["free", "-m"]
        if args.command == DiagnosticCommand.PS:
            if any((args.service, args.path, args.test)):
                raise InvalidToolArguments("ps accepts no arguments")
            return ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"]
        if args.command == DiagnosticCommand.CURL:
            if args.service is None:
                raise InvalidToolArguments("curl requires a service")
            authorize_service(self.permissions, args.service)
            path = args.path or "/health"
            if path not in {"/health", "/telemetry", "/observability/metrics"}:
                raise UnsafeOperation("curl path is not allowlisted")
            target = self.services.target(args.service)
            return ["curl", "--fail", "--silent", "--show-error", f"{target.base_url}{path}"]
        if args.command == DiagnosticCommand.PYTEST:
            if not args.test:
                raise InvalidToolArguments("pytest requires an allowlisted test target")
            if (
                args.test.startswith("-")
                or ".." in args.test
                or not re.fullmatch(r"backend/tests/[A-Za-z0-9_./:-]+", args.test)
            ):
                raise UnsafeOperation("pytest target is not allowlisted")
            return ["python", "-m", "pytest", "-q", args.test]
        raise UnsafeOperation("diagnostic command is not allowlisted")

    @staticmethod
    def _search_text(root: Path, query: str, limit: int) -> list[dict[str, object]]:
        if not root.exists():
            raise ServiceUnavailable(f"search root {root} is unavailable")
        needle = query.casefold()
        results: list[dict[str, object]] = []
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in files:
            if len(results) >= limit:
                break
            if not path.is_file() or ".git" in path.parts:
                continue
            if path.stat().st_size > 1_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if needle in line.casefold():
                    results.append(
                        {
                            "path": str(path.relative_to(root if root.is_dir() else root.parent)),
                            "line": line_no,
                            "text": line[:500],
                        }
                    )
                    if len(results) >= limit:
                        break
        return results

    @staticmethod
    def _run_command(command: list[str], cwd: Path | None, timeout: float) -> str:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolTimeout("diagnostic command timed out") from exc
        except (subprocess.CalledProcessError, OSError) as exc:
            raise ServiceUnavailable("diagnostic source is unavailable") from exc
        return completed.stdout
