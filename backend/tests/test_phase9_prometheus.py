from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.observability.persistence import ModelExecutionRecord
from app.observability.prometheus import SqlPrometheusExporter
from app.persistence.base import Base
from app.persistence.models import (
    AgentCheckpointRecord,
    AgentRunRecord,
    EvidenceRecord,
    IncidentRecord,
    ToolCallRecord,
)


def test_prometheus_projection_is_durable_bounded_and_privacy_safe() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    started_at = datetime.now(UTC)
    incident_id = "11111111-1111-1111-1111-111111111111"
    run_id = "22222222-2222-2222-2222-222222222222"
    scenario_canary = "PHASE9-SCENARIO-SECRET"
    argument_canary = "PHASE9-TOOL-ARGUMENT-SECRET"
    evidence_canary = "PHASE9-EVIDENCE-SECRET"

    with Session(engine) as session:
        session.add(
            IncidentRecord(
                id=incident_id,
                title="Prometheus projection test",
                description="Persist operational state without leaking incident content.",
                severity="P2",
                service="checkout",
                start_time=started_at,
                status="open",
                scenario_id=scenario_canary,
            )
        )
        session.add(
            AgentRunRecord(
                id=run_id,
                incident_id=incident_id,
                architecture_version="phase9-prometheus-test",
                model="local-placeholder",
                step_count=3,
                tool_call_count=1,
                token_usage=30,
                estimated_cost=0.003,
                status="completed",
            )
        )
        session.add(
            AgentCheckpointRecord(
                run_id=run_id,
                state={
                    "started_at": started_at.isoformat(),
                    "operation_stage": "investigation",
                },
                next_node="complete",
                revision=1,
                updated_at=started_at + timedelta(seconds=3),
            )
        )
        session.add(
            EvidenceRecord(
                id="33333333-3333-3333-3333-333333333333",
                incident_id=incident_id,
                run_id=run_id,
                source="phase9.query_metrics",
                evidence_type="metric",
                service="checkout",
                timestamp=started_at + timedelta(milliseconds=500),
                observation=evidence_canary,
                raw_reference=evidence_canary,
                reliability=1.0,
            )
        )
        session.add(
            ToolCallRecord(
                id="44444444-4444-4444-4444-444444444444",
                run_id=run_id,
                tool_name="query_metrics",
                arguments={"secret": argument_canary},
                started_at=started_at + timedelta(milliseconds=500),
                completed_at=started_at + timedelta(milliseconds=750),
                status="succeeded",
                result_reference="33333333-3333-3333-3333-333333333333",
                risk_level="R0",
            )
        )
        session.add_all(
            [
                ModelExecutionRecord(
                    id="55555555-5555-5555-5555-555555555555",
                    run_id=run_id,
                    operation="plan",
                    provider="local-placeholder",
                    input_tokens=10,
                    output_tokens=5,
                    estimated_cost=0.001,
                    latency_ms=100.0,
                    status="succeeded",
                    error_type=None,
                    recorded_at=started_at + timedelta(milliseconds=250),
                ),
                ModelExecutionRecord(
                    id="66666666-6666-6666-6666-666666666666",
                    run_id=run_id,
                    operation="diagnose",
                    provider="local-placeholder",
                    input_tokens=12,
                    output_tokens=3,
                    estimated_cost=0.002,
                    latency_ms=200.0,
                    status="succeeded",
                    error_type=None,
                    recorded_at=started_at + timedelta(seconds=2),
                ),
            ]
        )
        session.commit()

    rendered = SqlPrometheusExporter(engine).render().decode("utf-8")

    assert 'opssentinel_agent_runs{status="completed"} 1.0' in rendered
    assert "opssentinel_agent_token_usage 30.0" in rendered
    assert "opssentinel_agent_estimated_cost 0.003" in rendered
    assert 'opssentinel_tool_calls{status="succeeded",tool="query_metrics"} 1.0' in rendered
    assert 'opssentinel_evidence_items{type="metric"} 1.0' in rendered
    assert (
        'opssentinel_model_executions{operation="diagnose",status="succeeded"} 1.0'
        in rendered
    )
    assert 'opssentinel_model_token_usage{direction="input"} 22.0' in rendered
    assert 'opssentinel_model_token_usage{direction="output"} 8.0' in rendered
    assert "opssentinel_model_estimated_cost 0.003" in rendered
    assert (
        'opssentinel_run_latency_milliseconds{quantile="0.50",stage="diagnosis"} 2000.0'
        in rendered
    )
    assert (
        'opssentinel_run_latency_observations{stage="verified_resolution"} 0.0'
        in rendered
    )
    assert (
        'opssentinel_run_latency_milliseconds{quantile="0.50",stage="verified_resolution"}'
        not in rendered
    )

    for forbidden in (
        run_id,
        incident_id,
        scenario_canary,
        argument_canary,
        evidence_canary,
        "local-placeholder",
    ):
        assert forbidden not in rendered

    assert "scenario_id" not in rendered
    assert "arguments" not in rendered
    assert "raw_reference" not in rendered


@pytest.mark.parametrize(
    "label",
    ["run_id", "incident_id", "scenario_id", "service", "provider", "model"],
)
def test_prometheus_metric_surface_has_no_high_cardinality_identity_labels(label: str) -> None:
    source = SqlPrometheusExporter.render.__code__.co_consts
    assert label not in source
