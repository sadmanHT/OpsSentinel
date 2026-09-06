import pytest

from app.mcp.models import EvidenceEnvelope, PermissionSet, ToolCategory, ToolInvocation
from app.mcp.registry import RegisteredTool, ToolRegistry
from app.mcp.registry_support import EmptyArgs
from app.models.domain import EvidenceType, RiskLevel, ToolCallStatus


@pytest.mark.asyncio
async def test_r2_handler_requires_trusted_approval() -> None:
    called = 0

    async def handler(_args: EmptyArgs) -> EvidenceEnvelope:
        nonlocal called
        called += 1
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="test.r2",
            payload={"executed": True},
        )

    permissions = PermissionSet(
        principal="phase5-policy-test",
        allowed_tools={"r2_action"},
        allowed_services=set(),
    )
    registry = ToolRegistry(
        timeout_seconds=1.0,
        max_output_bytes=16_000,
        permissions=permissions,
    )
    registry.register(
        RegisteredTool(
            name="r2_action",
            description="Test reversible action.",
            category=ToolCategory.OPERATIONS,
            risk_level=RiskLevel.R2,
            args_model=EmptyArgs,
            handler=handler,
        )
    )

    blocked = await registry.invoke(ToolInvocation(tool="r2_action", arguments={}))
    assert blocked.status == ToolCallStatus.BLOCKED
    assert called == 0

    approved = await registry.invoke(
        ToolInvocation(tool="r2_action", arguments={}),
        trusted_approval_id="approval-123",
    )
    assert approved.status == ToolCallStatus.SUCCEEDED
    assert called == 1


@pytest.mark.asyncio
async def test_r3_handler_is_blocked_even_with_approval() -> None:
    called = 0

    async def handler(_args: EmptyArgs) -> EvidenceEnvelope:
        nonlocal called
        called += 1
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="test.r3",
            payload={"executed": True},
        )

    permissions = PermissionSet(
        principal="phase5-policy-test",
        allowed_tools={"r3_action"},
        allowed_services=set(),
    )
    registry = ToolRegistry(
        timeout_seconds=1.0,
        max_output_bytes=16_000,
        permissions=permissions,
    )
    registry.register(
        RegisteredTool(
            name="r3_action",
            description="Test destructive action.",
            category=ToolCategory.OPERATIONS,
            risk_level=RiskLevel.R3,
            args_model=EmptyArgs,
            handler=handler,
        )
    )

    response = await registry.invoke(
        ToolInvocation(tool="r3_action", arguments={}),
        trusted_approval_id="approval-123",
    )

    assert response.status == ToolCallStatus.BLOCKED
    assert called == 0
