import asyncio

import pytest

from app.mcp.models import EvidenceEnvelope, PermissionSet, ToolCategory, ToolInvocation
from app.mcp.registry import RegisteredTool, ToolRegistry
from app.mcp.registry_support import EmptyArgs
from app.models.domain import EvidenceType, RiskLevel, ToolCallStatus


def registry(*, timeout: float = 0.05, max_bytes: int = 1024) -> ToolRegistry:
    permissions = PermissionSet(
        principal="test",
        allowed_tools={"test_tool"},
        allowed_services=set(),
    )
    return ToolRegistry(
        timeout_seconds=timeout,
        max_output_bytes=max_bytes,
        permissions=permissions,
    )


def register(
    target: ToolRegistry,
    handler,
) -> None:
    target.register(
        RegisteredTool(
            "test_tool",
            "test",
            ToolCategory.DIAGNOSTICS,
            RiskLevel.R1,
            EmptyArgs,
            handler,
        )
    )


@pytest.mark.asyncio
async def test_registry_rejects_invalid_arguments() -> None:
    target = registry()

    async def handler(_args: EmptyArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source="test",
            payload={"ok": True},
        )

    register(target, handler)
    response = await target.invoke(ToolInvocation(tool="test_tool", arguments={"unexpected": True}))
    assert response.status == ToolCallStatus.BLOCKED
    assert response.error and response.error.code == "invalid_arguments"


@pytest.mark.asyncio
async def test_registry_enforces_timeout() -> None:
    target = registry(timeout=0.01)

    async def handler(_args: EmptyArgs) -> EvidenceEnvelope:
        await asyncio.sleep(0.1)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source="test",
            payload={"ok": True},
        )

    register(target, handler)
    response = await target.invoke(ToolInvocation(tool="test_tool"))
    assert response.status == ToolCallStatus.FAILED
    assert response.error and response.error.code == "timeout"


@pytest.mark.asyncio
async def test_registry_enforces_output_limit() -> None:
    target = registry(max_bytes=200)

    async def handler(_args: EmptyArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source="test",
            payload={"output": "x" * 2_000},
        )

    register(target, handler)
    response = await target.invoke(ToolInvocation(tool="test_tool"))
    assert response.status == ToolCallStatus.FAILED
    assert response.error and response.error.code == "result_too_large"


@pytest.mark.asyncio
async def test_registry_enforces_tool_permission() -> None:
    target = registry()
    target.permissions = PermissionSet(principal="restricted", allowed_tools=set())

    async def handler(_args: EmptyArgs) -> EvidenceEnvelope:
        raise AssertionError("handler should not run")

    register(target, handler)
    response = await target.invoke(ToolInvocation(tool="test_tool"))
    assert response.status == ToolCallStatus.BLOCKED
    assert response.error and response.error.code == "permission_denied"
