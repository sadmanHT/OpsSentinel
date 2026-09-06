import pytest

from evaluationlab.counterfactual import (
    CounterfactualObservation,
    adapt_counterfactual_observation,
    score_counterfactual_consistency,
)


def test_counterfactual_consistency_rewards_causal_change_and_noncausal_invariance() -> None:
    metrics = score_counterfactual_consistency(
        [
            CounterfactualObservation(
                family="deploy-cron-latency",
                variant="original",
                expected_root_cause_codes=["n_plus_one_query"],
                predicted_root_cause_codes=["N_PLUS_ONE"],
            ),
            CounterfactualObservation(
                family="deploy-cron-latency",
                variant="gap_then_cron",
                expected_root_cause_codes=["n_plus_one_query"],
                predicted_root_cause_codes=["n_plus_one_query"],
            ),
            CounterfactualObservation(
                family="deploy-cron-latency",
                variant="no_fault",
                expected_root_cause_codes=["no_fault"],
                predicted_root_cause_codes=["NO_FAULT"],
            ),
        ]
    )

    assert metrics.pair_count == 3
    assert metrics.consistency == 1.0
    assert metrics.causal_sensitivity == 1.0
    assert metrics.causal_invariance == 1.0


def test_counterfactual_consistency_detects_spurious_and_insensitive_predictions() -> None:
    metrics = score_counterfactual_consistency(
        [
            CounterfactualObservation(
                family="family-a",
                variant="a",
                expected_root_cause_codes=["memory_leak"],
                predicted_root_cause_codes=["MEMORY_LEAK"],
            ),
            CounterfactualObservation(
                family="family-a",
                variant="b",
                expected_root_cause_codes=["memory_leak"],
                predicted_root_cause_codes=["CONFIG_ERROR"],
            ),
            CounterfactualObservation(
                family="family-a",
                variant="c",
                expected_root_cause_codes=["no_fault"],
                predicted_root_cause_codes=["CONFIG_ERROR"],
            ),
        ]
    )

    assert metrics.pair_count == 3
    assert metrics.consistency == pytest.approx(1 / 3)
    assert metrics.causal_sensitivity == pytest.approx(1 / 2)
    assert metrics.causal_invariance == 0.0


def test_counterfactual_scoring_is_order_invariant_and_validates_family_contract() -> None:
    observations = [
        CounterfactualObservation(
            family="family-a",
            variant="b",
            expected_root_cause_codes=["no_fault"],
            predicted_root_cause_codes=["NO_FAULT"],
        ),
        CounterfactualObservation(
            family="family-a",
            variant="a",
            expected_root_cause_codes=["disk_exhaustion"],
            predicted_root_cause_codes=["DISK_EXHAUSTION"],
        ),
    ]
    forward = score_counterfactual_consistency(observations)
    reverse = score_counterfactual_consistency(list(reversed(observations)))
    assert forward.model_dump() == reverse.model_dump()

    with pytest.raises(ValueError, match="one family"):
        score_counterfactual_consistency(
            [
                observations[0],
                CounterfactualObservation(
                    family="family-b",
                    variant="other",
                    expected_root_cause_codes=["no_fault"],
                ),
            ]
        )
    with pytest.raises(ValueError, match="unique"):
        score_counterfactual_consistency([observations[0], observations[0]])


def test_counterfactual_adapter_uses_saved_phase6_scenario_and_artifact() -> None:
    scenario = {
        "scenario_id": "ops-v1-013",
        "kind": "counterfactual",
        "structure": {
            "counterfactual_family": "deploy-cron-latency",
            "counterfactual_variant": "original",
        },
        "ground_truth": {
            "primary_root_cause_code": "n_plus_one_query",
            "secondary_root_cause_codes": ["memory_leak"],
        },
    }
    artifact = {
        "scenario_id": "ops-v1-013",
        "diagnosis_code": "N_PLUS_ONE",
        "raw_agent_run": {
            "final_diagnosis": {
                "primary_root_cause": "n_plus_one_query",
                "secondary_root_causes": ["MEMORY_LEAK"],
            }
        },
    }

    observation = adapt_counterfactual_observation(scenario, artifact)
    assert observation.family == "deploy-cron-latency"
    assert observation.variant == "original"
    assert observation.expected_root_cause_codes == ["n_plus_one_query", "memory_leak"]
    assert observation.predicted_root_cause_codes == ["N_PLUS_ONE", "MEMORY_LEAK"]

    with pytest.raises(ValueError, match="scenario_id"):
        adapt_counterfactual_observation(scenario, {**artifact, "scenario_id": "other"})
    with pytest.raises(ValueError, match="counterfactual scenario"):
        adapt_counterfactual_observation({**scenario, "kind": "standard"}, artifact)
