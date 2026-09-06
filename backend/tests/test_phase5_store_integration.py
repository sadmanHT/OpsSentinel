import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.agent.models import (
    AgentBudget,
    AgentNode,
    AgentState,
    ApprovalDecision,
    ApprovalRequest,
    OperationStage,
    ProposedAction,
)
from app.agent.store import SqlAgentStore
from app.config import Settings
from app.models.domain import (
    AgentRunStatus,
    Evidence,
    EvidenceType,
    Incident,
    IncidentSeverity,
    RiskLevel,
    utc_now,
)
from app.persistence.session import create_database_engine


@pytest.mark.integration
def test_sql_store_persists_approval_checkpoint_and_audit_record() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["OPSSENTINEL_DATABASE_URL"])
    engine = create_database_engine(settings)
    store = SqlAgentStore(
        engine,
        architecture_version="phase5-test",
        model="deterministic-test",
    )
    incident = Incident(
        title="Approval persistence incident",
        description="Persist a human approval across checkpoint revisions.",
        severity=IncidentSeverity.P2,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="phase5-approval-persistence",
    )
    evidence = Evidence(
        incident_id=incident.id,
        source="test.phase5",
        evidence_type=EvidenceType.METRIC,
        service="checkout",
        timestamp=utc_now(),
        observation="Checkout query count is elevated.",
        raw_reference='{"payload":{"value":15}}',
    )
    action = ProposedAction(
        description="Rollback checkout in the sandbox.",
        risk_level=RiskLevel.R2,
        rationale="Evidence indicates a checkout regression.",
        evidence_ids=[evidence.id],
        tool="rollback_sandbox_deployment",
        arguments={"service": "checkout"},
    )
    approval = ApprovalRequest(
        action=action,
        why_proposed=action.rationale,
        evidence_ids=action.evidence_ids,
        expected_benefit=action.expected_benefit,
        possible_risk=action.possible_risk,
        rollback_strategy=action.rollback_strategy,
    )
    state = AgentState(
        run_id=uuid4(),
        incident=incident,
        status=AgentRunStatus.PAUSED,
        next_node=AgentNode.END,
        operational_mode=True,
        operation_stage=OperationStage.WAIT_APPROVAL,
        evidence=[evidence],
        budget=AgentBudget(),
        proposed_action=action,
        approval=approval,
        stop_reason="awaiting human approval for R2 sandbox action",
    )

    store.create(state)
    assert state.approval is not None
    state.approval.decision = ApprovalDecision.APPROVED
    state.approval.decided_at = utc_now()
    state.approval.decided_by = "incident-commander"
    state.updated_at = utc_now()
    store.save(state)

    loaded = store.load(state.run_id)
    assert loaded is not None
    assert loaded.approval is not None
    assert loaded.approval.id == approval.id
    assert loaded.approval.decision == ApprovalDecision.APPROVED
    assert loaded.approval.decided_by == "incident-commander"

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT decision, risk_level, action FROM approvals "
                "WHERE run_id = :run_id"
            ),
            {"run_id": str(state.run_id)},
        ).one()

    assert row.decision == ApprovalDecision.APPROVED.value
    assert row.risk_level == RiskLevel.R2.value
    assert row.action["tool"] == "rollback_sandbox_deployment"
    assert row.action["arguments"] == {"service": "checkout"}
