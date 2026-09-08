from __future__ import annotations

from uuid import UUID

import pytest

from researchlab.pareto_campaign import (
    PARETO_VALIDATION_SCENARIO_IDS,
    ParetoCampaignTrial,
    pareto_configuration,
)
from researchlab.pareto_live import ParetoArmArtifact, validate_pareto_arm


def _artifact(config_id: str = "p9-c01") -> ParetoArmArtifact:
    configuration = pareto_configuration(config_id)
    trials = [
        ParetoCampaignTrial(
            configuration=configuration.model_copy(deep=True),
            scenario_id=scenario_id,
            agent_run_id=UUID(int=index + 1),
            diagnostic_accuracy=1.0,
            exact_match=1.0,
            estimated_cost=0.0,
            total_tokens=0,
            tool_calls=2,
            retrieved_evidence=4,
            latency_seconds=0.1,
            no_fault_false_positive=(
                False if scenario_id == "ops-v1-040" else None
            ),
        )
        for index, scenario_id in enumerate(PARETO_VALIDATION_SCENARIO_IDS)
    ]
    return ParetoArmArtifact(
        benchmark_version="ops-v1",
        configuration=configuration,
        scenario_ids=list(PARETO_VALIDATION_SCENARIO_IDS),
        runtime_health={"status": "ok"},
        trials=trials,
        raw_records=[{"scenario_id": item.scenario_id} for item in trials],
    )


def test_valid_pareto_arm_is_accepted() -> None:
    artifact = _artifact()
    assert validate_pareto_arm(artifact) == artifact


def test_pareto_arm_rejects_configuration_drift() -> None:
    artifact = _artifact()
    artifact.configuration.model = "other"
    with pytest.raises(ValueError, match="differs from the frozen configuration"):
        validate_pareto_arm(artifact)


def test_pareto_arm_rejects_duplicate_scenarios() -> None:
    artifact = _artifact()
    artifact.trials[-1] = artifact.trials[0].model_copy(deep=True)
    with pytest.raises(ValueError, match="contains duplicate scenarios"):
        validate_pareto_arm(artifact)


def test_pareto_arm_rejects_raw_record_count_mismatch() -> None:
    artifact = _artifact()
    artifact.raw_records.pop()
    with pytest.raises(ValueError, match="one raw record per trial"):
        validate_pareto_arm(artifact)
