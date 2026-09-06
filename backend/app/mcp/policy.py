from app.mcp.errors import PermissionDenied, UnsafeOperation
from app.mcp.models import PermissionSet
from app.models.domain import RiskLevel


class RiskPolicy:
    """Enforce the Phase 3 R0-R3 action boundary."""

    def authorize(self, risk_level: RiskLevel, approval_id: str | None = None) -> None:
        if risk_level in {RiskLevel.R0, RiskLevel.R1}:
            return
        if risk_level == RiskLevel.R2:
            if approval_id:
                return
            raise PermissionDenied("R2 actions require explicit human approval")
        raise UnsafeOperation("R3 destructive actions are blocked")


def authorize_tool(permissions: PermissionSet, tool_name: str) -> None:
    if tool_name not in permissions.allowed_tools:
        raise PermissionDenied(f"principal {permissions.principal!r} cannot use {tool_name!r}")


def authorize_service(permissions: PermissionSet, service: str) -> None:
    if service not in permissions.allowed_services:
        raise PermissionDenied(
            f"principal {permissions.principal!r} cannot interact with service {service!r}"
        )
