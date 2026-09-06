from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass

from app.mcp.models import ToolDefinition, ToolError, ToolInvocation, ToolResponse
from app.mcp.registry import ToolRegistry
from app.models.domain import RiskLevel, ToolCallStatus, utc_now


@dataclass(frozen=True)
class RetryEvent:
    tool: str
    code: str
    message: str
    retryable: bool
    attempt: int


_retry_events: ContextVar[list[RetryEvent] | None] = ContextVar(
    "opssentinel_retry_events",
    default=None,
)


class RetryingToolRegistry(ToolRegistry):
    """Retry retryable tool failures while preserving the original safety policy.

    The wrapped registry remains the authority for permissions and R0-R3 policy. This
    decorator only decides whether a retryable failure should be attempted again. It
    also converts unexpected handler failures into bounded ToolResponses so an MCP
    integration defect cannot crash the Phase 5 agent runtime.
    """

    def __init__(
        self,
        inner: ToolRegistry,
        *,
        max_retries: int,
        backoff_seconds: float,
    ) -> None:
        super().__init__(
            timeout_seconds=inner.timeout_seconds,
            max_output_bytes=inner.max_output_bytes,
            permissions=inner.permissions,
            policy=inner.policy,
        )
        self.inner = inner
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._risk_by_tool = {
            definition.name: definition.risk_level for definition in inner.definitions()
        }

    def definitions(self) -> list[ToolDefinition]:
        return self.inner.definitions()

    def begin_capture(self) -> None:
        """Start an isolated retry-event buffer for one agent request/run.

        LangGraph may execute nodes in child async contexts. A mutable list stored in a
        ContextVar is inherited by reference, so child tasks can append retry events and
        the parent Phase 5 runtime can drain them after the graph returns. Each request
        receives a fresh list, preserving isolation between concurrent investigations.
        """

        _retry_events.set([])

    def _event_buffer(self) -> list[RetryEvent]:
        events = _retry_events.get()
        if events is None:
            events = []
            _retry_events.set(events)
        return events

    async def invoke(
        self,
        invocation: ToolInvocation,
        *,
        trusted_approval_id: str | None = None,
    ) -> ToolResponse:
        attempt = 1
        while True:
            try:
                response = await self.inner.invoke(
                    invocation,
                    trusted_approval_id=trusted_approval_id,
                )
            except Exception:
                now = utc_now()
                response = ToolResponse(
                    tool=invocation.tool,
                    status=ToolCallStatus.FAILED,
                    risk_level=self._risk_by_tool.get(invocation.tool, RiskLevel.R0),
                    started_at=now,
                    completed_at=utc_now(),
                    error=ToolError(
                        code="unexpected_tool_error",
                        message="tool execution failed unexpectedly or returned a malformed result",
                        retryable=False,
                    ),
                )

            if response.status == ToolCallStatus.SUCCEEDED:
                return response

            error = response.error
            event = RetryEvent(
                tool=invocation.tool,
                code=error.code if error is not None else response.status.value,
                message=(
                    error.message
                    if error is not None
                    else f"tool finished with status {response.status.value}"
                ),
                retryable=bool(error is not None and error.retryable),
                attempt=attempt,
            )
            self._event_buffer().append(event)

            should_retry = (
                response.status == ToolCallStatus.FAILED
                and error is not None
                and error.retryable
                and attempt <= self.max_retries
            )
            if not should_retry:
                return response

            if self.backoff_seconds > 0:
                await asyncio.sleep(self.backoff_seconds * attempt)
            attempt += 1

    def drain_failures(self) -> list[RetryEvent]:
        events = _retry_events.get()
        if not events:
            return []
        drained = list(events)
        events.clear()
        return drained
