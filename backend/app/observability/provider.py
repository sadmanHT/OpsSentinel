from __future__ import annotations

import json
import logging
from time import perf_counter

from opentelemetry.trace import Span

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
from app.observability.tracing import model_tracer

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

    def _generation_attributes(
        self,
        *,
        state: AgentState,
        operation: ModelOperation,
    ) -> dict[str, str]:
        return {
            "langfuse.observation.type": "generation",
            "langfuse.observation.model.name": self.name,
            "langfuse.observation.metadata.operation": operation.value,
            "langfuse.observation.metadata.runId": str(state.run_id),
            "opssentinel.model.operation": operation.value,
            "opssentinel.agent.run_id": str(state.run_id),
        }

    @staticmethod
    def _finish_generation_span(
        span: Span,
        *,
        usage: ProviderUsage,
        status: ModelExecutionStatus,
        error_type: str | None = None,
    ) -> None:
        usage_details = {
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "total": usage.total_tokens,
        }
        span.set_attribute(
            "langfuse.observation.usage_details",
            json.dumps(usage_details, separators=(",", ":"), sort_keys=True),
        )
        span.set_attribute(
            "langfuse.observation.cost_details",
            json.dumps(
                {"total": usage.estimated_cost},
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        span.set_attribute("opssentinel.model.status", status.value)
        if error_type is not None:
            span.set_attribute("opssentinel.model.error_type", error_type)

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        operation = ModelOperation.PLAN
        started_at = perf_counter()
        with model_tracer().start_as_current_span(
            f"model.{operation.value}",
            attributes=self._generation_attributes(state=state, operation=operation),
        ) as span:
            try:
                result = await self.inner.plan(state)
            except Exception as exc:
                usage = ProviderUsage()
                error_type = type(exc).__name__
                self._record(
                    state=state,
                    operation=operation,
                    started_at=started_at,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                self._finish_generation_span(
                    span,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                raise
            plan, usage = result
            self._record(
                state=state,
                operation=operation,
                started_at=started_at,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            self._finish_generation_span(
                span,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            return plan, usage

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        operation = ModelOperation.UPDATE_HYPOTHESES
        started_at = perf_counter()
        with model_tracer().start_as_current_span(
            f"model.{operation.value}",
            attributes=self._generation_attributes(state=state, operation=operation),
        ) as span:
            try:
                result = await self.inner.update_hypotheses(state)
            except Exception as exc:
                usage = ProviderUsage()
                error_type = type(exc).__name__
                self._record(
                    state=state,
                    operation=operation,
                    started_at=started_at,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                self._finish_generation_span(
                    span,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                raise
            hypotheses, usage = result
            self._record(
                state=state,
                operation=operation,
                started_at=started_at,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            self._finish_generation_span(
                span,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            return hypotheses, usage

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        operation = ModelOperation.ENOUGH_EVIDENCE
        started_at = perf_counter()
        with model_tracer().start_as_current_span(
            f"model.{operation.value}",
            attributes=self._generation_attributes(state=state, operation=operation),
        ) as span:
            try:
                result = await self.inner.enough_evidence(state)
            except Exception as exc:
                usage = ProviderUsage()
                error_type = type(exc).__name__
                self._record(
                    state=state,
                    operation=operation,
                    started_at=started_at,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                self._finish_generation_span(
                    span,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                raise
            enough, usage = result
            self._record(
                state=state,
                operation=operation,
                started_at=started_at,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            self._finish_generation_span(
                span,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            return enough, usage

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        operation = ModelOperation.DIAGNOSE
        started_at = perf_counter()
        with model_tracer().start_as_current_span(
            f"model.{operation.value}",
            attributes=self._generation_attributes(state=state, operation=operation),
        ) as span:
            try:
                result = await self.inner.diagnose(state)
            except Exception as exc:
                usage = ProviderUsage()
                error_type = type(exc).__name__
                self._record(
                    state=state,
                    operation=operation,
                    started_at=started_at,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                self._finish_generation_span(
                    span,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                raise
            code, diagnosis, usage = result
            self._record(
                state=state,
                operation=operation,
                started_at=started_at,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            self._finish_generation_span(
                span,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            return code, diagnosis, usage

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        operation = ModelOperation.RECOMMEND
        started_at = perf_counter()
        with model_tracer().start_as_current_span(
            f"model.{operation.value}",
            attributes=self._generation_attributes(state=state, operation=operation),
        ) as span:
            try:
                result = await self.inner.recommend(state)
            except Exception as exc:
                usage = ProviderUsage()
                error_type = type(exc).__name__
                self._record(
                    state=state,
                    operation=operation,
                    started_at=started_at,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                self._finish_generation_span(
                    span,
                    usage=usage,
                    status=ModelExecutionStatus.FAILED,
                    error_type=error_type,
                )
                raise
            action, usage = result
            self._record(
                state=state,
                operation=operation,
                started_at=started_at,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            self._finish_generation_span(
                span,
                usage=usage,
                status=ModelExecutionStatus.SUCCEEDED,
            )
            return action, usage
