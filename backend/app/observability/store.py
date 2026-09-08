from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.observability.models import (
    LatencyDistribution,
    ModelExecutionEvent,
    ModelExecutionStatus,
    ModelOperation,
    RunCostSummary,
)
from app.observability.persistence import ModelExecutionRecord
from app.persistence.models import (
    AgentCheckpointRecord,
    AgentRunRecord,
    EvidenceRecord,
    ToolCallRecord,
)
from app.persistence.session import create_session_factory


class ModelExecutionSink(Protocol):
    def record_model_execution(self, event: ModelExecutionEvent) -> None: ...


class InMemoryObservabilityStore:
    def __init__(self) -> None:
        self.events: list[ModelExecutionEvent] = []

    def record_model_execution(self, event: ModelExecutionEvent) -> None:
        self.events.append(event.model_copy(deep=True))

    def events_for(self, run_id: UUID) -> list[ModelExecutionEvent]:
        return [event.model_copy(deep=True) for event in self.events if event.run_id == run_id]


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    if quantile < 0.0 or quantile > 1.0:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def latency_distribution(values: list[float]) -> LatencyDistribution:
    return LatencyDistribution(
        count=len(values),
        p50_ms=percentile(values, 0.50),
        p95_ms=percentile(values, 0.95),
    )


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _duration_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds() * 1000.0)


class SqlObservabilityStore:
    def __init__(self, engine: Engine) -> None:
        self.session_factory: sessionmaker[Session] = create_session_factory(engine)

    def record_model_execution(self, event: ModelExecutionEvent) -> None:
        with self.session_factory() as session:
            session.add(
                ModelExecutionRecord(
                    id=str(event.id),
                    run_id=str(event.run_id),
                    operation=event.operation.value,
                    provider=event.provider,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    estimated_cost=event.estimated_cost,
                    latency_ms=event.latency_ms,
                    status=event.status.value,
                    error_type=event.error_type,
                    recorded_at=event.recorded_at,
                )
            )
            session.commit()

    def summarize(self, run_id: UUID) -> RunCostSummary | None:
        with self.session_factory() as session:
            run = session.get(AgentRunRecord, str(run_id))
            if run is None:
                return None
            events = list(
                session.scalars(
                    select(ModelExecutionRecord).where(
                        ModelExecutionRecord.run_id == str(run_id)
                    )
                ).all()
            )
            tool_calls = list(
                session.scalars(
                    select(ToolCallRecord).where(ToolCallRecord.run_id == str(run_id))
                ).all()
            )
            evidence = list(
                session.scalars(
                    select(EvidenceRecord).where(EvidenceRecord.run_id == str(run_id))
                ).all()
            )
            checkpoint = session.get(AgentCheckpointRecord, str(run_id))

            input_tokens = sum(event.input_tokens for event in events)
            output_tokens = sum(event.output_tokens for event in events)
            provider_cost = sum(event.estimated_cost for event in events)
            model_latencies = [event.latency_ms for event in events]
            tool_latencies = [
                max(0.0, (call.completed_at - call.started_at).total_seconds() * 1000.0)
                for call in tool_calls
                if call.completed_at is not None
            ]

            run_started_at: datetime | None = None
            if checkpoint is not None:
                run_started_at = _as_datetime(checkpoint.state.get("started_at"))

            first_candidates = [event.recorded_at for event in events]
            first_candidates.extend(call.started_at for call in tool_calls)
            first_step_at = min(first_candidates) if first_candidates else None

            diagnosis_times = [
                event.recorded_at
                for event in events
                if event.operation == ModelOperation.DIAGNOSE.value
                and event.status == ModelExecutionStatus.SUCCEEDED.value
            ]
            diagnosis_at = min(diagnosis_times) if diagnosis_times else None

            return RunCostSummary(
                run_id=run_id,
                status=run.status,
                model=run.model,
                model_execution_count=len(events),
                failed_model_execution_count=sum(
                    event.status == ModelExecutionStatus.FAILED.value for event in events
                ),
                usage_breakdown_available=bool(events),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=run.token_usage,
                provider_estimated_cost=provider_cost,
                total_estimated_cost=run.estimated_cost,
                tool_call_count=len(tool_calls),
                retrieval_depth=len(evidence),
                model_latency=latency_distribution(model_latencies),
                tool_latency=latency_distribution(tool_latencies),
                time_to_first_investigation_step_ms=_duration_ms(
                    run_started_at, first_step_at
                ),
                time_to_diagnosis_ms=_duration_ms(run_started_at, diagnosis_at),
                time_to_verified_resolution_ms=None,
            )
