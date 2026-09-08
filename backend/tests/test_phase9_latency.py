import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.agent.models import AgentBudget, AgentState, OperationStage, VerificationResult
from app.agent.store import SqlAgentStore
from app.config import Settings
from app.models.domain import (
    AgentRunStatus,
    Incident,
    IncidentSeverity,
    VerificationStatus,
)
from app.observability.models import ModelExecutionEvent, ModelOperation
from app.observability.store import SqlObservabilityStore
from app.persistence.session import create_database_engine


def _incident(label: str) -> Incident:
    return Incident(
        title=f"Phase 9 latency test {label}",
        description="Exercise durable latency aggregation without fabricating missing timings.",
        severity=IncidentSeverity.P2,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id=f"phase9-latency-{label}",
    )


def _record_timing_events(
    store: SqlObservabilityStore,
    *,
    run_id: object,
    started_at: datetime,
    first_step_ms: int,
    diagnosis_ms: int,
) -> None:
    from uuid import UUID

    assert isinstance(run_id, UUID)
    store.record_model_execution(
        ModelExecutionEvent(
            run_id=run_id,
            operation=ModelOperation.PLAN,
            provider="phase9-latency-test-provider",
            latency_ms=10.0,
            recorded_at=started_at + timedelta(milliseconds=first_step_ms),
        )
    )
    store.record_model_execution(
        ModelExecutionEvent(
            run_id=run_id,
            operation=ModelOperation.DIAGNOSE,
            provider="phase9-latency-test-provider",
            latency_ms=20.0,
            recorded_at=started_at + timedelta(milliseconds=diagnosis_ms),
        )
    )


@pytest.mark.integration
def test_verified_resolution_and_latency_aggregate_exclude_nonpassed_runs() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["OPSSENTINEL_DATABASE_URL"])
    engine = create_database_engine(settings)
    agent_store = SqlAgentStore(
        engine,
        architecture_version="phase9-latency-test",
        model="phase9-latency-test-provider",
    )
    observability_store = SqlObservabilityStore(engine)

    passed_started_at = datetime.now(UTC)
    passed_state = AgentState(
        run_id=uuid4(),
        incident=_incident("passed"),
        status=AgentRunStatus.COMPLETED,
        operational_mode=True,
        operation_stage=OperationStage.COMPLETE,
        verification=VerificationResult(
            status=VerificationStatus.PASSED,
            summary="Deterministic post-action verification passed.",
        ),
        started_at=passed_started_at,
        updated_at=passed_started_at + timedelta(seconds=3),
        budget=AgentBudget(tokens_used=20, cost_used=0.002),
    )
    agent_store.create(passed_state)
    _record_timing_events(
        observability_store,
        run_id=passed_state.run_id,
        started_at=passed_started_at,
        first_step_ms=500,
        diagnosis_ms=2000,
    )

    failed_started_at = passed_started_at + timedelta(seconds=10)
    failed_state = AgentState(
        run_id=uuid4(),
        incident=_incident("failed"),
        status=AgentRunStatus.COMPLETED,
        operational_mode=True,
        operation_stage=OperationStage.COMPLETE,
        verification=VerificationResult(
            status=VerificationStatus.FAILED,
            summary="Verification ran but did not observe the expected healthy state.",
        ),
        started_at=failed_started_at,
        updated_at=failed_started_at + timedelta(seconds=4),
        budget=AgentBudget(tokens_used=25, cost_used=0.003),
    )
    agent_store.create(failed_state)
    _record_timing_events(
        observability_store,
        run_id=failed_state.run_id,
        started_at=failed_started_at,
        first_step_ms=1000,
        diagnosis_ms=3000,
    )

    passed_summary = observability_store.summarize(passed_state.run_id)
    assert passed_summary is not None
    assert passed_summary.time_to_verified_resolution_ms == pytest.approx(3000.0)

    failed_summary = observability_store.summarize(failed_state.run_id)
    assert failed_summary is not None
    assert failed_summary.time_to_verified_resolution_ms is None

    aggregate = observability_store.summarize_latency(
        [passed_state.run_id, failed_state.run_id]
    )
    assert aggregate.run_count == 2

    first_step = aggregate.time_to_first_investigation_step
    assert first_step.count == 2
    assert first_step.p50_ms == pytest.approx(750.0)
    assert first_step.p95_ms == pytest.approx(975.0)

    diagnosis = aggregate.time_to_diagnosis
    assert diagnosis.count == 2
    assert diagnosis.p50_ms == pytest.approx(2500.0)
    assert diagnosis.p95_ms == pytest.approx(2950.0)

    verified = aggregate.time_to_verified_resolution
    assert verified.count == 1
    assert verified.p50_ms == pytest.approx(3000.0)
    assert verified.p95_ms == pytest.approx(3000.0)
