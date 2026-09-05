from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.domain import (
    Evidence,
    EvidenceType,
    Hypothesis,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCall,
)

NOW = datetime.now(timezone.utc)


def test_incident_accepts_valid_values() -> None:
    incident = Incident(
        title="Checkout latency",
        description="p95 latency increased after a deployment",
        severity=IncidentSeverity.P1,
        service="checkout",
        start_time=NOW,
    )
    assert incident.status.value == "open"
    assert incident.service == "checkout"


def test_incident_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        Incident(
            title="Bad incident",
            description="invalid severity",
            severity="P9",  # type: ignore[arg-type]
            service="checkout",
            start_time=NOW,
        )


def test_evidence_reliability_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            incident_id=uuid4(),
            source="prometheus",
            evidence_type=EvidenceType.METRIC,
            timestamp=NOW,
            observation="p95 increased",
            reliability=1.5,
        )


def test_hypothesis_rejects_cause_after_effect() -> None:
    with pytest.raises(ValidationError):
        Hypothesis(
            description="Impossible timeline",
            root_cause_code="TEST",
            confidence=0.5,
            first_possible_cause_time=NOW + timedelta(minutes=1),
            effect_time=NOW,
        )


def test_tool_call_rejects_completion_before_start() -> None:
    with pytest.raises(ValidationError):
        ToolCall(
            tool_name="query_metrics",
            arguments={},
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
            risk_level=RiskLevel.R0,
        )
