from __future__ import annotations

from typing import Any

from pydantic import Field

from researchlab.models import StrictModel
from researchlab.pareto import ParetoConfiguration
from researchlab.pareto_campaign import (
    CAMPAIGN_INTERPRETATION,
    PARETO_VALIDATION_SCENARIO_IDS,
    ParetoCampaignTrial,
    pareto_configuration,
)


class ParetoArmArtifact(StrictModel):
    experiment: str = "phase9_pareto_optimization"
    interpretation: str = CAMPAIGN_INTERPRETATION
    benchmark_version: str = Field(min_length=1, max_length=80)
    configuration: ParetoConfiguration
    scenario_ids: list[str]
    runtime_health: dict[str, object]
    trials: list[ParetoCampaignTrial]
    raw_records: list[dict[str, Any]]


def validate_pareto_arm(artifact: ParetoArmArtifact) -> ParetoArmArtifact:
    expected = pareto_configuration(artifact.configuration.id)
    if artifact.configuration != expected:
        raise ValueError(
            f"Pareto arm {artifact.configuration.id} differs from the frozen configuration"
        )
    expected_ids = list(PARETO_VALIDATION_SCENARIO_IDS)
    if artifact.scenario_ids != expected_ids:
        raise ValueError(
            f"Pareto arm {artifact.configuration.id} does not use the frozen validation cohort"
        )
    if len(artifact.trials) != len(expected_ids):
        raise ValueError(
            f"Pareto arm {artifact.configuration.id} requires {len(expected_ids)} trials"
        )
    observed_ids = [trial.scenario_id for trial in artifact.trials]
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError(f"Pareto arm {artifact.configuration.id} contains duplicate scenarios")
    if sorted(observed_ids) != sorted(expected_ids):
        raise ValueError(
            f"Pareto arm {artifact.configuration.id} trial cohort does not match the frozen cohort"
        )
    if any(trial.configuration != expected for trial in artifact.trials):
        raise ValueError(
            f"Pareto arm {artifact.configuration.id} contains a trial from another configuration"
        )
    if len(artifact.raw_records) != len(expected_ids):
        raise ValueError(
            f"Pareto arm {artifact.configuration.id} requires one raw record per trial"
        )
    return artifact
