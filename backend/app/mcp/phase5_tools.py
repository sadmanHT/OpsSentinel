import asyncio
import re
import subprocess
from pathlib import Path

from app.config import Settings
from app.mcp.errors import InvalidToolArguments, ServiceUnavailable, ToolTimeout, UnsafeOperation
from app.mcp.models import (
    EvidenceEnvelope,
    ExecuteSqlArgs,
    ExplainAnalyzeArgs,
    PermissionSet,
    ReproduceRequestArgs,
    RerunLoadTestArgs,
    RunTestsArgs,
    SandboxServiceArgs,
)
from app.mcp.policy import authorize_service
from app.mcp.services import SandboxActuatorClient, ServiceClient
from app.mcp.tools import InvestigationTools
from app.models.domain import EvidenceType


class Phase5Tools:
    """Deterministic verification and reversible sandbox-only operational tools."""

    _request_allowlist = {
        ("gateway", "GET", "/health"),
        ("gateway", "GET", "/checkout"),
        ("checkout", "GET", "/health"),
        ("checkout", "GET", "/orders"),
        ("inventory", "GET", "/health"),
        ("inventory", "GET", "/inventory/SKU-RED"),
        ("payment", "GET", "/health"),
        ("payment", "POST", "/charge"),
        ("worker", "GET", "/health"),
        ("worker", "POST", "/work"),
        ("backend", "GET", "/health"),
    }

    def __init__(
        self,
        settings: Settings,
        permissions: PermissionSet,
        *,
        service_client: ServiceClient | None = None,
        actuator_client: SandboxActuatorClient | None = None,
    ) -> None:
        self.settings = settings
        self.permissions = permissions
        self.services = service_client or ServiceClient(settings, permissions)
        self.actuator = actuator_client or SandboxActuatorClient(settings, permissions)
        self.investigation = InvestigationTools(
            settings,
            permissions,
            service_client=self.services,
        )

    async def run_tests(self, args: RunTestsArgs) -> EvidenceEnvelope:
        if (
            args.test.startswith("-")
            or ".." in args.test
            or not re.fullmatch(r"backend/tests/[A-Za-z0-9_./:-]+", args.test)
        ):
            raise UnsafeOperation("pytest target is not allowlisted")
        output = await asyncio.to_thread(
            self._run_command,
            ["python", "-m", "pytest", "-q", args.test],
            self.settings.mcp_repo_root,
            self.settings.mcp_diagnostic_timeout_seconds,
        )
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="mcp.run_tests",
            payload={"test": args.test, "passed": True, "output": output[:16_000]},
            truncated=len(output) > 16_000,
        )

    async def reproduce_request(self, args: ReproduceRequestArgs) -> EvidenceEnvelope:
        authorize_service(self.permissions, args.service)
        method = args.method.upper()
        if (args.service, method, args.path) not in self._request_allowlist:
            raise UnsafeOperation(
                "request target is not allowlisted for deterministic verification"
            )
        status, payload = await self.services.request(args.service, method, args.path)
        expected = args.expected_status
        passed = status == expected if expected is not None else 200 <= status < 400
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="mcp.reproduce_request",
            service=args.service,
            payload={
                "method": method,
                "path": args.path,
                "status": status,
                "expected_status": expected,
                "passed": passed,
                "response": payload,
            },
        )

    async def rerun_load_test(self, args: RerunLoadTestArgs) -> EvidenceEnvelope:
        if args.path != "/checkout":
            raise InvalidToolArguments("Phase 5 load verification is limited to /checkout")
        request_count = {"normal": 20, "burst": 30, "sustained": 40}[args.profile]
        errors = 0
        statuses: dict[int, int] = {}
        for _ in range(request_count):
            status, _payload = await self.services.request("gateway", "GET", args.path)
            statuses[status] = statuses.get(status, 0) + 1
            if status >= 400:
                errors += 1
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="mcp.rerun_load_test",
            service="gateway",
            payload={
                "profile": args.profile,
                "path": args.path,
                "requests": request_count,
                "errors": errors,
                "statuses": statuses,
                "passed": errors == 0,
            },
        )

    async def explain_analyze(self, args: ExplainAnalyzeArgs) -> EvidenceEnvelope:
        query = args.query.strip().rstrip(";")
        if not re.match(r"(?is)^select\b", query):
            raise InvalidToolArguments("EXPLAIN ANALYZE verification accepts a SELECT query")
        evidence = await self.investigation.execute_sql(
            ExecuteSqlArgs(
                query=f"EXPLAIN (ANALYZE, FORMAT JSON) {query}",
                max_rows=args.max_rows,
            )
        )
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="mcp.explain_analyze",
            payload=evidence.payload,
            truncated=evidence.truncated,
        )

    async def restart_sandbox_service(self, args: SandboxServiceArgs) -> EvidenceEnvelope:
        payload = await self.actuator.restart(args.service)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="mcp.restart_sandbox_service",
            service=args.service,
            payload={"action_executed": True, "receipt": payload},
        )

    async def rollback_sandbox_deployment(self, args: SandboxServiceArgs) -> EvidenceEnvelope:
        payload = await self.actuator.rollback(args.service)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="mcp.rollback_sandbox_deployment",
            service=args.service,
            payload={"action_executed": True, "receipt": payload},
        )

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
            raise ToolTimeout("verification command timed out") from exc
        except subprocess.CalledProcessError as exc:
            output = (exc.stdout or "") + (exc.stderr or "")
            raise ServiceUnavailable(f"verification test failed: {output[:400]}") from exc
        except OSError as exc:
            raise ServiceUnavailable("verification source is unavailable") from exc
        return completed.stdout
