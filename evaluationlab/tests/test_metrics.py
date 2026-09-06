import pytest

from evaluationlab import (
    EvaluationCase,
    EvaluationEngine,
    EvidenceUtility,
    ToolCallAssessment,
    ToolCallOutcome,
    brier_score,
    canonical_root_cause,
    expected_calibration_error,
    score_evidence,
    score_root_causes,
)
from evaluationlab.models import FailureCategory, SafetyObservation


def test_root_cause_aliases_preserve_phase6_ground_truth_without_rewriting_it() -> None:
    assert canonical_root_cause("n_plus_one_query") == "N_PLUS_ONE"
    assert canonical_root_cause("database_connection_leak") == "CONNECTION_POOL_EXHAUSTION"
    assert canonical_root_cause("broken_payment_configuration") == "CONFIG_ERROR"


def test_perfect_prediction_has_accuracy_one() -> None:
    metrics = score_root_causes("n_plus_one_query", [], "N_PLUS_ONE", [])
    assert metrics.primary_accuracy == 1.0
    assert metrics.secondary_recall == 1.0
    assert metrics.multi_root_cause_precision == 1.0
    assert metrics.multi_root_cause_recall == 1.0
    assert metrics.exact_match is True


def test_compound_prediction_with_one_of_two_causes_gets_partial_credit() -> None:
    metrics = score_root_causes(
        "n_plus_one_query",
        ["memory_leak"],
        "N_PLUS_ONE",
        [],
    )
    assert metrics.primary_accuracy == 1.0
    assert metrics.secondary_recall == 0.0
    assert metrics.multi_root_cause_precision == 1.0
    assert metrics.multi_root_cause_recall == 0.5
    assert metrics.exact_match is False


def test_zero_selected_relevant_evidence_has_zero_recall() -> None:
    metrics = score_evidence([], ["metric:pool"], ["metric:pool"], [])
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.critical_recall == 0.0


def test_brier_and_ece_are_zero_for_perfect_calibration_dataset() -> None:
    confidences = [0.0, 1.0]
    outcomes = [0.0, 1.0]
    assert brier_score(confidences, outcomes) == 0.0
    assert expected_calibration_error(confidences, outcomes, n_bins=2) == 0.0


def test_metric_inputs_reject_length_mismatch() -> None:
    with pytest.raises(ValueError, match="equal length"):
        brier_score([0.5], [0.0, 1.0])


def test_engine_is_deterministic_and_classifies_failed_compound_run() -> None:
    case = EvaluationCase(
        benchmark_version="1.0.0",
        scenario_id="compound-001",
        expected_primary_root_cause_code="n_plus_one_query",
        expected_secondary_root_cause_codes=["memory_leak"],
        predicted_primary_root_cause_code="n_plus_one_query",
        confidence=0.9,
        selected_evidence_tags=["log:distractor"],
        relevant_evidence_tags=["metric:db_queries", "metric:memory"],
        critical_evidence_tags=["metric:db_queries", "metric:memory"],
        distractor_tags=["log:distractor"],
        tool_calls=[
            ToolCallAssessment(
                tool_name="query_metrics",
                signature="query_metrics:checkout",
                outcome=ToolCallOutcome.SUCCEEDED,
                utility=EvidenceUtility.IRRELEVANT,
            ),
            ToolCallAssessment(
                tool_name="query_metrics",
                signature="query_metrics:checkout",
                outcome=ToolCallOutcome.SUCCEEDED,
                utility=EvidenceUtility.REPEATED,
            ),
        ],
        safety=SafetyObservation(),
    )
    engine = EvaluationEngine()
    first = engine.evaluate(case)
    second = engine.evaluate(case)
    assert first.model_dump() == second.model_dump()
    assert first.root_cause.primary_accuracy == 1.0
    assert first.root_cause.multi_root_cause_recall == 0.5
    categories = {item.category for item in first.failure_classifications}
    assert FailureCategory.COMPOUND_CAUSE_OMISSION in categories
    assert FailureCategory.MISSED_EVIDENCE in categories
    assert FailureCategory.DISTRACTOR_CAPTURE in categories
    assert FailureCategory.OVER_INVESTIGATION in categories
    assert FailureCategory.OVERCONFIDENCE in categories


def test_aggregate_evaluation_is_reproducible() -> None:
    cases = [
        EvaluationCase(
            benchmark_version="1.0.0",
            scenario_id="easy-correct",
            expected_primary_root_cause_code="memory_leak",
            predicted_primary_root_cause_code="MEMORY_LEAK",
            confidence=1.0,
            selected_evidence_tags=["metric:memory"],
            relevant_evidence_tags=["metric:memory"],
            critical_evidence_tags=["metric:memory"],
        ),
        EvaluationCase(
            benchmark_version="1.0.0",
            scenario_id="easy-wrong",
            expected_primary_root_cause_code="memory_leak",
            predicted_primary_root_cause_code="CONFIG_ERROR",
            confidence=0.0,
            selected_evidence_tags=["metric:memory"],
            relevant_evidence_tags=["metric:memory"],
            critical_evidence_tags=["metric:memory"],
        ),
    ]
    engine = EvaluationEngine()
    first = engine.evaluate_many(cases, calibration_bins=2)
    second = engine.evaluate_many(cases, calibration_bins=2)
    assert first.model_dump() == second.model_dump()
    assert first.root_cause_accuracy == 0.5
    assert first.brier_score == 0.0
    assert first.expected_calibration_error == 0.0
