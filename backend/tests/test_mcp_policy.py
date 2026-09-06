import pytest

from app.mcp.errors import PermissionDenied, UnsafeOperation
from app.mcp.policy import RiskPolicy
from app.models.domain import RiskLevel


def test_r0_and_r1_are_automatic() -> None:
    policy = RiskPolicy()
    policy.authorize(RiskLevel.R0)
    policy.authorize(RiskLevel.R1)


def test_r2_requires_human_approval() -> None:
    policy = RiskPolicy()
    with pytest.raises(PermissionDenied):
        policy.authorize(RiskLevel.R2)
    policy.authorize(RiskLevel.R2, "approval-123")


def test_r3_is_always_blocked() -> None:
    with pytest.raises(UnsafeOperation):
        RiskPolicy().authorize(RiskLevel.R3, "approval-123")
