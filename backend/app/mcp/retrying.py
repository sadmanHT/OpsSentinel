from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass

from app.mcp.models import ToolDefinition, ToolInvocation, ToolResponse
from app.mcp.registry import ToolRegistry
from app.models.domain import ToolCallStatus


@dataclass(frozen=True)
class RetryEvent:
    tool: str
    code: str
    message: str
    retryable: bool
    attempt: int


_retry_events: ContextVar[tuple[RetryEvent, ...]] = ContextVar(
    "opssentinel_retry_events",
    default=(),
)


class RetryingToolRegistry(ToolRegistry):
    """Retry retryable tool failures while preserving the original safety policy.

    The wrapped registry remains the authority for permissions and R0-R3 policy. This
    decorator only decides whether a retryable failure should be attempted again.
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

    def definitions(self) -> list[ToolDefinition]:
        return self.inner.definitions()

    async def invoke(
        self,
        invocation: ToolInvocation,
        *,
        trusted_approval_id: str | None = None,
    ) -> ToolResponse:
        attempt = 1
        while True:
            response = await self.inner.invoke(
                invocation,
                trusted_approval_id=trusted_approval_id,
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
            _retry_events.set((*_retry_events.get(), event))

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
        events = list(_retry_events.get())
        _retry_events.set(())
        return events
