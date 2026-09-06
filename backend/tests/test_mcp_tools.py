from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.mcp.errors import PermissionDenied, ServiceUnavailable, UnsafeOperation
from app.mcp.models import (
    PermissionSet,
    QueryMetricsArgs,
    RunDiagnosticArgs,
    SearchDocumentationArgs,
    SearchLogsArgs,
)
from app.mcp.services import ServiceClient
from app.mcp.tools import InvestigationTools


def permissions() -> PermissionSet:
    return PermissionSet(
        principal="test-agent",
        allowed_tools=set(),
        allowed_services={"checkout", "worker"},
    )


@pytest.mark.asyncio
async def test_logs_and_metrics_are_structured_and_bounded() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/observability/logs"):
            return httpx.Response(
                200,
                json=[
                    {
                        "timestamp": "2026-09-06T00:00:00Z",
                        "level": "INFO",
                        "event": "request_completed",
                        "service": "checkout",
                        "method": "GET",
                        "path": "/orders",
                        "status": 200,
                        "latency_ms": 10.0,
                        "db_queries": 1,
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "metric": "db_query_count",
                "service": "checkout",
                "value": 1.0,
                "unit": "queries",
                "aggregation": "latest",
                "sample_count": 1,
                "start_time": None,
                "end_time": None,
            },
        )

    settings = Settings(mcp_checkout_url="http://checkout")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service_client = ServiceClient(settings, permissions(), client)
        tools = InvestigationTools(settings, permissions(), service_client)
        logs = await tools.search_logs(SearchLogsArgs(service="checkout", limit=1))
        metrics = await tools.query_metrics(
            QueryMetricsArgs(metric="db_query_count", service="checkout")
        )
    assert logs.payload[0]["service"] == "checkout"
    assert metrics.payload["metric"] == "db_query_count"


@pytest.mark.asyncio
async def test_unavailable_service_is_reported() -> None:
    def transport(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    settings = Settings(mcp_checkout_url="http://checkout")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        tools = InvestigationTools(
            settings,
            permissions(),
            ServiceClient(settings, permissions(), client),
        )
        with pytest.raises(ServiceUnavailable):
            await tools.search_logs(SearchLogsArgs(service="checkout"))


@pytest.mark.asyncio
async def test_unauthorized_service_is_rejected_before_network() -> None:
    settings = Settings()
    tools = InvestigationTools(settings, permissions())
    with pytest.raises(PermissionDenied):
        await tools.search_logs(SearchLogsArgs(service="payment"))


@pytest.mark.asyncio
async def test_documentation_path_traversal_fails(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "runbook.md").write_text("checkout database query runbook")
    tools = InvestigationTools(Settings(mcp_docs_root=docs, mcp_repo_root=tmp_path), permissions())
    result = await tools.search_documentation(
        SearchDocumentationArgs(query="database", path="runbook.md")
    )
    assert result.payload[0]["line"] == 1
    with pytest.raises(UnsafeOperation):
        await tools.search_documentation(
            SearchDocumentationArgs(query="database", path="../secret")
        )


@pytest.mark.asyncio
async def test_diagnostic_shell_escape_and_arbitrary_commands_fail(tmp_path: Path) -> None:
    tools = InvestigationTools(Settings(mcp_repo_root=tmp_path), permissions())
    with pytest.raises(UnsafeOperation):
        await tools.run_diagnostic(
            RunDiagnosticArgs(command="curl", service="worker", path="/;id")
        )
    with pytest.raises(ValidationError):
        RunDiagnosticArgs(command="bash")
