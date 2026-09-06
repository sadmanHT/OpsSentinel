from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.mcp.errors import ServiceUnavailable, ToolTimeout, UnsafeOperation
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

    async def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, object]:
        target = self.target(service)
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.mcp_tool_timeout_seconds)
        try:
            response = await client.request(
                method,
                f"{target.base_url}{path}",
                params=params,
                json=json_body,
            )
            try:
                data: object = response.json()
            except ValueError:
                data = response.text[:2_000]
            return response.status_code, data
        except httpx.TimeoutException as exc:
            raise ToolTimeout(f"{service} timed out") from exc
        except httpx.RequestError as exc:
            raise ServiceUnavailable(f"{service} is unavailable") from exc
        finally:
            if owns_client:
                assert client is not None
                await client.aclose()

    async def get_json(
        self,
        service: str,
        path: str,
        params: dict[str, str | int] | None = None,
    ) -> object:
        status, data = await self.request(service, "GET", path, params=params)
        if status >= 400:
            raise ServiceUnavailable(f"{service} returned HTTP {status}")
        return data


class SandboxActuatorClient:
    """Constrained client for reversible simulator-only operational actions."""

    allowed_services = {"gateway", "checkout", "inventory", "payment", "worker"}

    def __init__(
        self,
        settings: Settings,
        permissions: PermissionSet,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.permissions = permissions
        self._client = http_client

    async def restart(self, service: str) -> object:
        return await self._post("restart", service)

    async def rollback(self, service: str) -> object:
        return await self._post("rollback", service)

    async def _post(self, operation: str, service: str) -> object:
        authorize_service(self.permissions, service)
        if service not in self.allowed_services:
            raise UnsafeOperation("sandbox operations are limited to simulator services")
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.settings.mcp_tool_timeout_seconds)
        try:
            response = await client.post(
                f"{self.settings.sandbox_actuator_url.rstrip('/')}/operations/{operation}/{service}"
            )
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise ServiceUnavailable("sandbox actuator returned malformed JSON") from exc
        except httpx.TimeoutException as exc:
            raise ToolTimeout("sandbox actuator timed out") from exc
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ServiceUnavailable("sandbox actuator is unavailable") from exc
        finally:
            if owns_client:
                assert client is not None
                await client.aclose()
