import os
from datetime import UTC, datetime
from uuid import UUID

from app.persistence.models import AgentRunRecord, EvaluationScoreRecord, IncidentRecord
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from evaluationlab.counterfactual import (
    CounterfactualObservation,
    score_counterfactual_consistency,
)
from evaluationlab.engine import EvaluationEngine
from evaluationlab.models import EvaluationCase, FailureCategory
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    SqlEvaluationStore,
)

DATABASE_URL = os.environ["OPSSENTINEL_DATABASE_URL"]


def test_postgres_migration_and_evaluation_persistence_round_trip() -> None:
    engine = create_engine(DATABASE_URL)
    incident_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    agent_run_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    evaluation_run_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

    with Session(engine) as session:
        session.add(
            IncidentRecord(
                id=str(incident_id),
                title="Phase 7 persistence integration incident",
                description="Synthetic incident used to verify evaluator persistence.",
                severity="P2",
                service="checkout",
                start_time=datetime(2026, 9, 6, 16, 0, tzinfo=UTC),
                status="resolved",
                scenario_id="phase7-postgres-persistence",
            )
        )
        session.flush()
        session.add(
            AgentRunRecord(
                id=str(agent_run_id),
                incident_id=str(incident_id),
                architecture_version="phase5-safe-operational-agent-v1",
                model="deterministic",
                step_count=6,
                tool_call_count=4,
                token_usage=0,
                estimated_cost=0.0,
                status="completed",
            )
        )
        session.commit()

    case = EvaluationCase(
        benchmark_version="1.0.0",
        scenario_id="phase7-postgres-persistence",
        expected_primary_root_cause_code="n_plus_one_query",
        predicted_primary_root_cause_code="memory_leak",
        confidence=0.9,
        selected_evidence_tags=[],
        relevant_evidence_tags=["metric:db_query_count"],
        critical_evidence_tags=["metric:db_query_count"],
    )
    result = EvaluationEngine().evaluate(case)
    run = EvaluationRunMetadata(
        id=evaluation_run_id,
        dataset_version="benchmark-1.0.0",
        architecture_version="phase5-safe-operational-agent-v1",
        model="deterministic",
        seed=42,
        configuration={"calibration_bins": 10, "source": "phase7-ci"},
        created_at=datetime(2026, 9, 6, 16, 5, tzinfo=UTC),
    )
    experiment = ExperimentConfiguration(
        prompt_version="phase7-v1",
        scenario_version="1.0.0",
        evaluation_version="0.1.0",
        retrieval_settings={"mode": "bounded"},
        tool_budget=15,
        recorded_at=datetime(2026, 9, 6, 16, 6, tzinfo=UTC),
    )
    trace = {
        "agent_run_id": str(agent_run_id),
        "trajectory": {"tool_calls": 4, "final_status": "completed"},
    }
    counterfactual_metrics = score_counterfactual_consistency(
        [
            CounterfactualObservation(
                family="deploy-cron-latency",
                variant="original",
                expected_root_cause_codes=["database_connection_leak"],
                predicted_root_cause_codes=["database_connection_leak"],
            ),
            CounterfactualObservation(
                family="deploy-cron-latency",
                variant="gap_then_cron",
                expected_root_cause_codes=["database_connection_leak"],
                predicted_root_cause_codes=["database_connection_leak"],
            ),
            CounterfactualObservation(
                family="deploy-cron-latency",
                variant="deploy_cron_disabled",
                expected_root_cause_codes=["no_fault"],
                predicted_root_cause_codes=["no_fault"],
            ),
        ]
    )
    counterfactual_trace = {
        "family": counterfactual_metrics.family,
        "variant_count": counterfactual_metrics.variant_count,
    }

    store = SqlEvaluationStore(engine)
    store.create_run(run, experiment)
    store.save_result(
        evaluation_run_id,
        result,
        agent_run_id=agent_run_id,
        trace=trace,
    )
    store.save_counterfactual_metrics(
        evaluation_run_id,
        counterfactual_metrics,
        trace=counterfactual_trace,
    )
    engine.dispose()

    restarted_engine = create_engine(DATABASE_URL)
    restarted_store = SqlEvaluationStore(restarted_engine)
    loaded_run = restarted_store.load_run(evaluation_run_id)
    loaded_experiment = restarted_store.load_experiment(evaluation_run_id)
    loaded_result = restarted_store.load_result(evaluation_run_id, result.scenario_id)
    loaded_counterfactual = restarted_store.load_counterfactual_metrics(
        evaluation_run_id,
        counterfactual_metrics.family,
    )

    assert loaded_run is not None
    assert loaded_run.dataset_version == run.dataset_version
    assert loaded_run.architecture_version == run.architecture_version
    assert loaded_run.configuration == run.configuration
    assert loaded_experiment is not None
    assert loaded_experiment.model_dump() == experiment.model_dump()
    assert loaded_result is not None
    assert loaded_result.agent_run_id == agent_run_id
    assert loaded_result.result.model_dump() == result.model_dump()
    assert loaded_result.trace == trace
    assert FailureCategory.MISSED_EVIDENCE in loaded_result.failure_categories
    assert FailureCategory.OVERCONFIDENCE in loaded_result.failure_categories
    assert loaded_counterfactual is not None
    assert loaded_counterfactual.model_dump() == counterfactual_metrics.model_dump()
    assert restarted_store.counterfactual_metric_names(
        evaluation_run_id,
        counterfactual_metrics.family,
    ) == [
        "counterfactual.causal_invariance",
        "counterfactual.causal_sensitivity",
        "counterfactual.consistency",
    ]

    with Session(restarted_engine) as session:
        persisted_score = session.scalar(
            select(EvaluationScoreRecord).where(
                EvaluationScoreRecord.evaluation_run_id == str(evaluation_run_id),
                EvaluationScoreRecord.scenario_id == result.scenario_id,
                EvaluationScoreRecord.metric_name == "correctness",
            )
        )
        assert persisted_score is not None
        assert persisted_score.agent_run_id == str(agent_run_id)
        assert persisted_score.trace == trace
        assert persisted_score.failure_categories == [
            item.category.value for item in result.failure_classifications
        ]

        persisted_counterfactual = session.scalar(
            select(EvaluationScoreRecord).where(
                EvaluationScoreRecord.evaluation_run_id == str(evaluation_run_id),
                EvaluationScoreRecord.scenario_id == "counterfactual:deploy-cron-latency",
                EvaluationScoreRecord.metric_name == "counterfactual.consistency",
            )
        )
        assert persisted_counterfactual is not None
        assert persisted_counterfactual.agent_run_id is None
        assert persisted_counterfactual.score == counterfactual_metrics.consistency
        assert persisted_counterfactual.trace == counterfactual_trace
        assert persisted_counterfactual.failure_categories == []
        assert persisted_counterfactual.details["counterfactual_metrics"] == (
            counterfactual_metrics.model_dump(mode="json")
        )

    restarted_engine.dispose()
