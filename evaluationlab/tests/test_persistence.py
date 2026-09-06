from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)

from evaluationlab.engine import EvaluationEngine
from evaluationlab.models import EvaluationCase, FailureCategory
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    SqlEvaluationStore,
)


def _sqlite_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table("agent_runs", metadata, Column("id", String(36), primary_key=True))
    Table(
        "evaluation_runs",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("dataset_version", String(80), nullable=False),
        Column("architecture_version", String(80), nullable=False),
        Column("model", String(120), nullable=False),
        Column("seed", Integer, nullable=False),
        Column("configuration", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    Table(
        "evaluation_scores",
        metadata,
        Column("id", String(36), primary_key=True),
        Column(
            "evaluation_run_id",
            String(36),
            ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column(
            "agent_run_id",
            String(36),
            ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        Column("scenario_id", String(120), nullable=False),
        Column("metric_name", String(120), nullable=False),
        Column("score", Float, nullable=False),
        Column("details", JSON, nullable=False),
        Column("trace", JSON, nullable=False),
        Column("failure_categories", JSON, nullable=False),
    )
    Table(
        "experiment_metadata",
        metadata,
        Column("id", String(36), primary_key=True),
        Column(
            "evaluation_run_id",
            String(36),
            ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        ),
        Column("prompt_version", String(80), nullable=False),
        Column("scenario_version", String(80), nullable=False),
        Column("evaluation_version", String(80), nullable=False),
        Column("retrieval_settings", JSON, nullable=False),
        Column("tool_budget", Integer, nullable=False),
        Column("recorded_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    return engine


def _result():
    case = EvaluationCase(
        benchmark_version="1.0.0",
        scenario_id="persist-known-answer",
        expected_primary_root_cause_code="n_plus_one_query",
        predicted_primary_root_cause_code="memory_leak",
        confidence=0.95,
        selected_evidence_tags=[],
        relevant_evidence_tags=["metric:db_query_count"],
        critical_evidence_tags=["metric:db_query_count"],
    )
    return EvaluationEngine().evaluate(case)


def test_persistence_round_trip_survives_store_restart_and_is_idempotent() -> None:
    engine = _sqlite_engine()
    run_id = UUID("11111111-1111-1111-1111-111111111111")
    agent_run_id = UUID("22222222-2222-2222-2222-222222222222")
    run = EvaluationRunMetadata(
        id=run_id,
        dataset_version="benchmark-1.0.0",
        architecture_version="agent-0.5.0",
        model="deterministic-local",
        seed=7,
        configuration={"calibration_bins": 10},
        created_at=datetime(2026, 9, 6, 16, 0, tzinfo=UTC),
    )
    experiment = ExperimentConfiguration(
        prompt_version="phase7-v1",
        scenario_version="1.0.0",
        evaluation_version="0.1.0",
        retrieval_settings={"strategy": "bounded"},
        tool_budget=15,
        recorded_at=datetime(2026, 9, 6, 16, 1, tzinfo=UTC),
    )
    result = _result()
    trace = {"agent_run_id": str(agent_run_id), "tool_history": ["query_metrics"]}

    store = SqlEvaluationStore(engine)
    store.create_run(run, experiment)
    store.save_result(run_id, result, agent_run_id=agent_run_id, trace=trace)

    restarted_store = SqlEvaluationStore(engine)
    loaded = restarted_store.load_result(run_id, result.scenario_id)
    assert loaded is not None
    assert loaded.agent_run_id == agent_run_id
    assert loaded.result.model_dump() == result.model_dump()
    assert loaded.trace == trace
    assert loaded.failure_categories == [
        classification.category for classification in result.failure_classifications
    ]
    assert FailureCategory.MISSED_EVIDENCE in loaded.failure_categories
    assert FailureCategory.OVERCONFIDENCE in loaded.failure_categories

    first_metric_names = restarted_store.metric_names(run_id, result.scenario_id)
    assert "correctness" in first_metric_names
    assert "root_cause.primary_accuracy" in first_metric_names
    assert "evidence.critical_recall" in first_metric_names

    restarted_store.save_result(
        run_id,
        result,
        agent_run_id=agent_run_id,
        trace={"revision": 2},
    )
    second_metric_names = restarted_store.metric_names(run_id, result.scenario_id)
    assert second_metric_names == first_metric_names
    updated = restarted_store.load_result(run_id, result.scenario_id)
    assert updated is not None
    assert updated.trace == {"revision": 2}


def test_persistence_rejects_duplicate_or_unknown_runs() -> None:
    engine = _sqlite_engine()
    run = EvaluationRunMetadata(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        dataset_version="benchmark-1.0.0",
        architecture_version="agent-0.5.0",
        model="deterministic-local",
        seed=1,
    )
    store = SqlEvaluationStore(engine)
    store.create_run(run)
    with pytest.raises(ValueError, match="already exists"):
        store.create_run(run)

    unknown_run = UUID("44444444-4444-4444-4444-444444444444")
    with pytest.raises(ValueError, match="does not exist"):
        store.save_result(unknown_run, _result())
    assert store.load_result(run.id, "missing") is None
