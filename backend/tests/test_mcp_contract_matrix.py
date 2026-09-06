import asyncio

import pytest

from app.mcp.errors import ServiceUnavailable
from app.mcp.models import EvidenceEnvelope, PermissionSet, ToolInvocation
from app.mcp.registry import ToolRegistry, build_registry
from app.models.domain import EvidenceType, ToolCallStatus

TOOL_CASES = [
    ("search_logs", {"service": "checkout"}),
    ("query_metrics", {"metric": "error_rate", "service": "checkout"}),
    ("execute_sql", {"query": "SELECT 1"}),
    ("list_deployments", {}),
    ("inspect_deployment", {"service": "checkout"}),
    ("inspect_commit", {"revision": "HEAD"}),
    ("inspect_git_diff", {"base": "HEAD", "head": "HEAD"}),
    ("search_code", {"query": "RiskPolicy"}),
    ("search_documentation", {"query": "ChaosLab"}),
    ("run_diagnostic", {"command": "df"}),
]


def registry() -> ToolRegistry:
    target = build_registry()
    target.timeout_seconds = 0.01
    target.max_output_bytes = 512
    return target


def evidence(payload: object = None) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        evidence_type=EvidenceType.DIAGNOSTIC,
        source="contract-test",
        payload={"ok": True} if payload is None else payload,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "arguments"), TOOL_CASES)
async def test_every_tool_accepts_a_valid_invocation(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    target = registry()

    async def handler(_args: object) -> EvidenceEnvelope:
        return evidence()

    target._tools[tool_name].handler = handler
    response = await target.invoke(ToolInvocation(tool=tool_name, arguments=arguments))
    assert response.status == ToolCallStatus.SUCCEEDED
    assert response.data is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "arguments"), TOOL_CASES)
async def test_every_tool_rejects_invalid_arguments(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    target = registry()
    invalid = {**arguments, "unexpected": True}
    response = await target.invoke(ToolInvocation(tool=tool_name, arguments=invalid))
    assert response.status == ToolCallStatus.BLOCKED
    assert response.error is not None
    assert response.error.code == "invalid_arguments"


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "arguments"), TOOL_CASES)
async def test_every_tool_enforces_timeout(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    target = registry()

    async def handler(_args: object) -> EvidenceEnvelope:
        await asyncio.sleep(0.05)
        return evidence()

    target._tools[tool_name].handler = handler
    response = await target.invoke(ToolInvocation(tool=tool_name, arguments=arguments))
    assert response.status == ToolCallStatus.FAILED
    assert response.error is not None
    assert response.error.code == "timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "arguments"), TOOL_CASES)
async def test_every_tool_reports_unavailable_source(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    target = registry()

    async def handler(_args: object) -> EvidenceEnvelope:
        raise ServiceUnavailable("source unavailable")

    target._tools[tool_name].handler = handler
    response = await target.invoke(ToolInvocation(tool=tool_name, arguments=arguments))
    assert response.status == ToolCallStatus.FAILED
    assert response.error is not None
    assert response.error.code == "service_unavailable"
    assert response.error.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "arguments"), TOOL_CASES)
async def test_every_tool_enforces_output_bound(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    target = registry()

    async def handler(_args: object) -> EvidenceEnvelope:
        return evidence({"output": "x" * 5_000})

    target._tools[tool_name].handler = handler
    response = await target.invoke(ToolInvocation(tool=tool_name, arguments=arguments))
    assert response.status == ToolCallStatus.FAILED
    assert response.error is not None
    assert response.error.code == "result_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "arguments"), TOOL_CASES)
async def test_every_tool_enforces_permission(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    target = registry()
    target.permissions = PermissionSet(
        principal="restricted-agent",
        allowed_tools=set(target.permissions.allowed_tools) - {tool_name},
        allowed_services=set(target.permissions.allowed_services),
    )
    response = await target.invoke(ToolInvocation(tool=tool_name, arguments=arguments))
    assert response.status == ToolCallStatus.BLOCKED
    assert response.error is not None
    assert response.error.code == "permission_denied"
