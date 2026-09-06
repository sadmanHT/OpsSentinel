from dataclasses import dataclass

import httpx

from app.config import Settings
from app.mcp.errors import ServiceUnavailable, ToolTimeout
from app.mcp.models import PermissionSet
from app.mcp.policy import authorize_service


@dataclass(frozen=True)
class ServiceTarget:
    name: str
    base_url: str
    deployment: str


def service_targets(settings: Settings) -> dict[str, ServiceTarget]:
    return {
        "backend": ServiceTarget("backend", settings.mcp_backend_url, "opssentinel-backend"),
        "gateway": ServiceTarget("gateway", settings.mcp_gateway_url, "chaoslab-gateway"),
        "checkout": ServiceTarget("checkout", settings.mcp_checkout_url, "chaoslab-checkout"),
        "inventory": ServiceTarget("inventory", settings.mcp_inventory_url, "chaoslab-inventory"),
        "payment": ServiceTarget("payment", settings.mcp_payment_url, "chaoslab-payment"),
        "worker": ServiceTarget("worker", settings.mcp_worker_url, "chaoslab-worker"),
    }


class ServiceClient:
    def __init__(
        self,
        settings: Settings,
        permissions: PermissionSet,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.permissions = permissions
        self.targets = service_targets(settings)
        self._client = http_client

    def target(self, service: str) -> ServiceTarget:
        authorize_service(self.permissions, service)
        target = self.targets.get(service)
        if target is None:
            raise ServiceUnavailable(f"service {service!r} is not an approved investigation target")
        return target

    async def get_json(
        self,
        service: str,
        path: str,
        params: dict[str, str | int] | None = None,
    ) -> object:
        target = self.target(service)
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.mcp_tool_timeout_seconds)
        try:
            response = await client.get(f"{target.base_url}{path}", params=params)
            response.raise_for_status()
            data: object = response.json()
            return data
        except httpx.TimeoutException as exc:
            raise ToolTimeout(f"{service} timed out") from exc
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ServiceUnavailable(f"{service} is unavailable") from exc
        finally:
            if owns_client:
                await client.aclose()
