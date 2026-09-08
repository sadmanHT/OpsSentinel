from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.observability.experiments import SqlExperimentDashboardStore
from app.persistence.base import Base
from app.persistence.models import (
    EvaluationRunRecord,
    EvaluationScoreRecord,
    ExperimentMetadataRecord,
)


def _score(
    *,
    evaluation_run_id: str,
    scenario_id: str,
    metric_name: str,
    score: float,
    failure_categories: list[str] | None = None,
) -> EvaluationScoreRecord:
    return EvaluationScoreRecord(
        id=str(uuid4()),
        evaluation_run_id=evaluation_run_id,
        agent_run_id=None,
        scenario_id=scenario_id,
        metric_name=metric_name,
        score=score,
        details={},
        trace={},
        failure_categories=failure_categories or [],
    )


def test_experiment_dashboard_reads_persisted_evaluation_records() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    run_id = str(uuid4())
    older_run_id = str(uuid4())

    with Session(engine) as session:
        session.add_all(
            [
                EvaluationRunRecord(
                    id=run_id,
                    dataset_version="benchmark-v9",
                    architecture_version="explicit-planner-v1",
                    model="local-placeholder",
                    seed=7,
                    configuration={"evidence_mode": "verification_enabled"},
                    created_at=now,
                ),
                EvaluationRunRecord(
                    id=older_run_id,
                    dataset_version="benchmark-v8",
                    architecture_version="reactive-react-v1",
                    model="local-placeholder",
                    seed=3,
                    configuration={},
                    created_at=now - timedelta(days=1),
                ),
                ExperimentMetadataRecord(
                    id=str(uuid4()),
                    evaluation_run_id=run_id,
                    prompt_version="prompt-v9",
                    scenario_version="scenario-v9",
                    evaluation_version="evaluation-v9",
                    retrieval_settings={"depth": 20},
                    tool_budget=15,
                    recorded_at=now,
                ),
            ]
        )
        session.add_all(
            [
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-a",
                    metric_name="correctness",
                    score=1.0,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-a",
                    metric_name="confidence",
                    score=0.8,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-a",
                    metric_name="root_cause.primary_accuracy",
                    score=1.0,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-a",
                    metric_name="evidence.precision",
                    score=0.5,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-a",
                    metric_name="evidence.recall",
                    score=0.6,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-a",
                    metric_name="efficiency.total_tool_calls",
                    score=4.0,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-a",
                    metric_name="safety.unsafe_action_attempts",
                    score=0.0,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-b",
                    metric_name="correctness",
                    score=0.0,
                    failure_categories=["root_cause_miss"],
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-b",
                    metric_name="confidence",
                    score=0.4,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-b",
                    metric_name="root_cause.primary_accuracy",
                    score=0.0,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-b",
                    metric_name="efficiency.total_tool_calls",
                    score=6.0,
                ),
                _score(
                    evaluation_run_id=run_id,
                    scenario_id="scenario-b",
                    metric_name="safety.unsafe_action_attempts",
                    score=1.0,
                ),
            ]
        )
        session.commit()

    dashboard = SqlExperimentDashboardStore(engine).list_runs(limit=10)

    assert dashboard.run_count == 2
    latest = dashboard.runs[0]
    assert str(latest.evaluation_run_id) == run_id
    assert latest.dataset_version == "benchmark-v9"
    assert latest.configuration == {"evidence_mode": "verification_enabled"}
    assert latest.retrieval_settings == {"depth": 20}
    assert latest.tool_budget == 15
    assert latest.scenario_count == 2
    assert latest.linked_agent_run_count == 0
    assert latest.metrics.correctness_mean == pytest.approx(0.5)
    assert latest.metrics.confidence_mean == pytest.approx(0.6)
    assert latest.metrics.primary_root_cause_accuracy_mean == pytest.approx(0.5)
    assert latest.metrics.evidence_precision_mean == pytest.approx(0.5)
    assert latest.metrics.evidence_recall_mean == pytest.approx(0.6)
    assert latest.metrics.total_tool_calls_mean == pytest.approx(5.0)
    assert latest.metrics.unsafe_action_attempts_total == pytest.approx(1.0)
    assert latest.failure_categories == {"root_cause_miss": 1}

    older = dashboard.runs[1]
    assert older.scenario_count == 0
    assert older.metrics.correctness_mean is None
    assert older.metrics.unsafe_action_attempts_total is None
    assert older.tool_budget is None


def test_experiment_dashboard_rejects_unbounded_limits() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = SqlExperimentDashboardStore(engine)

    with pytest.raises(ValueError, match="between 1 and 100"):
        store.list_runs(limit=0)

    with pytest.raises(ValueError, match="between 1 and 100"):
        store.list_runs(limit=101)
