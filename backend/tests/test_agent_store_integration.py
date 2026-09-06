import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.agent.models import AgentBudget, AgentNode, AgentState
from app.agent.store import SqlAgentStore
from app.config import Settings
from app.models.domain import (
    AgentRunStatus,
    Diagnosis,
    Evidence,
    EvidenceType,
    Hypothesis,
    HypothesisStatus,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCall,
    ToolCallStatus,
    VerificationStatus,
)
from app.persistence.session import create_database_engine


@pytest.mark.integration
def test_sql_agent_store_round_trips_full_checkpoint_state() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["OPSSENTINEL_DATABASE_URL"])
    engine = create_database_engine(settings)
    store = SqlAgentStore(
        engine,
        architecture_version="phase4-test",
        model="deterministic-test",
    )

    incident = Incident(
        title="Persistent checkout incident",
        description="Exercise the durable Phase 4 checkpoint store.",
        severity=IncidentSeverity.P2,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="checkpoint-integration",
    )
    evidence = Evidence(
        incident_id=incident.id,
        source="test.query_metrics",
        evidence_type=EvidenceType.METRIC,
        service="checkout",
        timestamp=datetime.now(UTC),
        observation="Checkout DB query count is elevated.",
        raw_reference='{"payload":{"value":15}}',
    )
    hypothesis = Hypothesis(
        description="Checkout performs excessive database queries.",
        root_cause_code="n_plus_one_query",
        confidence=0.97,
        supporting_evidence=[evidence.id],
        status=HypothesisStatus.CONFIRMED,
    )
    call = ToolCall(
        id=uuid4(),
        tool_name="query_metrics",
        arguments={"service": "checkout", "metric": "db_query_count"},
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        status=ToolCallStatus.SUCCEEDED,
        result_reference=str(evidence.id),
        risk_level=RiskLevel.R0,
    )
    diagnosis = Diagnosis(
        primary_root_cause=hypothesis.description,
        confidence=hypothesis.confidence,
        evidence_ids=[evidence.id],
        recommended_actions=["Batch the repeated checkout query path."],
        verification_status=VerificationStatus.NOT_RUN,
    )
    state = AgentState(
        run_id=uuid4(),
        incident=incident,
        status=AgentRunStatus.PAUSED,
        next_node=AgentNode.DIAGNOSE,
        evidence=[evidence],
        hypotheses=[hypothesis],
        tool_history=[call],
        current_hypothesis=hypothesis.id,
        confidence=hypothesis.confidence,
        budget=AgentBudget(steps_used=1, tool_calls_used=1),
        diagnosis_code="n_plus_one_query",
        final_diagnosis=diagnosis,
        stop_reason="integration checkpoint",
    )

    store.create(state)
    state.budget.steps_used = 2
    state.updated_at = datetime.now(UTC)
    store.save(state)

    loaded = store.load(state.run_id)
    assert loaded is not None
    assert loaded.run_id == state.run_id
    assert loaded.next_node == AgentNode.DIAGNOSE
    assert loaded.status == AgentRunStatus.PAUSED
    assert loaded.evidence[0].id == evidence.id
    assert loaded.hypotheses[0].supporting_evidence == [evidence.id]
    assert loaded.tool_history[0].result_reference == str(evidence.id)
    assert loaded.final_diagnosis is not None
    assert loaded.final_diagnosis.evidence_ids == [evidence.id]
    assert loaded.budget.steps_used == 2

    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT revision FROM agent_checkpoints WHERE run_id = :run_id"),
            {"run_id": str(state.run_id)},
        ).scalar_one()
        persisted = connection.execute(
            text(
                "SELECT COUNT(*) FROM evidence WHERE run_id = :run_id"
            ),
            {"run_id": str(state.run_id)},
        ).scalar_one()

    assert revision >= 2
    assert persisted == 1
