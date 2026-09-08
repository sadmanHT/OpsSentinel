from __future__ import annotations

import logging
from time import perf_counter

from app.agent.models import (
    AgentState,
    InvestigationPlan,
    ProposedAction,
    ProviderUsage,
)
from app.agent.providers import ReasoningProvider
from app.models.domain import Diagnosis, Hypothesis
from app.observability.models import (
    ModelExecutionEvent,
    ModelExecutionStatus,
    ModelOperation,
)
from app.observability.store import ModelExecutionSink

logger = logging.getLogger(__name__)


class MeteredReasoningProvider:
    """Observe provider executions without changing the provider identity or outputs."""

    def __init__(self, inner: ReasoningProvider, sink: ModelExecutionSink) -> None:
        self.inner = inner
        self.sink = sink
        self.name = inner.name

    def _record(
        self,
        *,
        state: AgentState,
        operation: ModelOperation,
        started_at: float,
        usage: ProviderUsage,
        status: ModelExecutionStatus,
        error_type: str | None = None,
    ) -> None:
        event = ModelExecutionEvent(
            run_id=state.run_id,
            operation=operation,
            provider=self.name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            estimated_cost=usage.estimated_cost,
            latency_ms=max(0.0, (perf_counter() - started_at) * 1000.0),
            status=status,
            error_type=error_type,
        )
        try:
            self.sink.record_model_execution(event)
        except Exception:
            logger.exception(
                "Phase 9 model-execution metering write failed",
                extra={"run_id": str(state.run_id), "operation": operation.value},
            )

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        started_at = perf_counter()
        try:
            result = await self.inner.plan(state)
        except Exception as exc:
            self._record(
                state=state,
                operation=ModelOperation.PLAN,
                started_at=started_at,
                usage=ProviderUsage(),
                status=ModelExecutionStatus.FAILED,
                error_type=type(exc).__name__,
            )
            raise
        plan, usage = result
        self._record(
            state=state,
            operation=ModelOperation.PLAN,
            started_at=started_at,
            usage=usage,
            status=ModelExecutionStatus.SUCCEEDED,
        )
        return plan, usage

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        started_at = perf_counter()
        try:
            result = await self.inner.update_hypotheses(state)
        except Exception as exc:
            self._record(
                state=state,
                operation=ModelOperation.UPDATE_HYPOTHESES,
                started_at=started_at,
                usage=ProviderUsage(),
                status=ModelExecutionStatus.FAILED,
                error_type=type(exc).__name__,
            )
            raise
        hypotheses, usage = result
        self._record(
            state=state,
            operation=ModelOperation.UPDATE_HYPOTHESES,
            started_at=started_at,
            usage=usage,
            status=ModelExecutionStatus.SUCCEEDED,
        )
        return hypotheses, usage

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        started_at = perf_counter()
        try:
            result = await self.inner.enough_evidence(state)
        except Exception as exc:
            self._record(
                state=state,
                operation=ModelOperation.ENOUGH_EVIDENCE,
                started_at=started_at,
                usage=ProviderUsage(),
                status=ModelExecutionStatus.FAILED,
                error_type=type(exc).__name__,
            )
            raise
        enough, usage = result
        self._record(
            state=state,
            operation=ModelOperation.ENOUGH_EVIDENCE,
            started_at=started_at,
            usage=usage,
            status=ModelExecutionStatus.SUCCEEDED,
        )
        return enough, usage

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        started_at = perf_counter()
        try:
            result = await self.inner.diagnose(state)
        except Exception as exc:
            self._record(
                state=state,
                operation=ModelOperation.DIAGNOSE,
                started_at=started_at,
                usage=ProviderUsage(),
                status=ModelExecutionStatus.FAILED,
                error_type=type(exc).__name__,
            )
            raise
        code, diagnosis, usage = result
        self._record(
            state=state,
            operation=ModelOperation.DIAGNOSE,
            started_at=started_at,
            usage=usage,
            status=ModelExecutionStatus.SUCCEEDED,
        )
        return code, diagnosis, usage

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        started_at = perf_counter()
        try:
            result = await self.inner.recommend(state)
        except Exception as exc:
            self._record(
                state=state,
                operation=ModelOperation.RECOMMEND,
                started_at=started_at,
                usage=ProviderUsage(),
                status=ModelExecutionStatus.FAILED,
                error_type=type(exc).__name__,
            )
            raise
        action, usage = result
        self._record(
            state=state,
            operation=ModelOperation.RECOMMEND,
            started_at=started_at,
            usage=usage,
            status=ModelExecutionStatus.SUCCEEDED,
        )
        return action, usage
