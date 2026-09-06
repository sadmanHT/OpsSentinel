from __future__ import annotations

import pytest

from researchlab.models import (
    MAX_DATABASE_SEED,
    Difficulty,
    ExperimentPlan,
    ExperimentSplit,
    ScenarioRef,
    make_trial_identity,
)
from researchlab.plans import build_phase8_plans


def _scenario(*, scenario_version: str = "1.0.0") -> ScenarioRef:
    return ScenarioRef(
        scenario_id="ops-v1-001",
        scenario_version=scenario_version,
        split=ExperimentSplit.VALIDATION,
        difficulty=Difficulty.EASY,
    )


def test_trial_identity_and_seed_are_deterministic_and_database_safe() -> None:
    plan = build_phase8_plans(repeat_count=2)[0]
    cell = plan.cells[0]
    scenario = _scenario()

    first = make_trial_identity(plan, cell, scenario, 0)
    replay = make_trial_identity(plan, cell, scenario, 0)
    repeated = make_trial_identity(plan, cell, scenario, 1)

    assert first == replay
    assert first.trial_id != repeated.trial_id
    assert first.seed != repeated.seed
    assert 0 <= first.seed <= MAX_DATABASE_SEED
    assert 0 <= repeated.seed <= MAX_DATABASE_SEED


def test_trial_identity_changes_with_dataset_configuration_and_scenario_version() -> None:
    plan = build_phase8_plans()[0]
    baseline = make_trial_identity(plan, plan.cells[0], _scenario(), 0)

    changed_dataset_payload = plan.model_dump(mode="python")
    changed_dataset_payload["dataset_version"] = "1.0.1"
    changed_dataset = ExperimentPlan.model_validate(changed_dataset_payload)

    changed_config_payload = plan.model_dump(mode="python")
    for cell in changed_config_payload["cells"]:
        cell["configuration"]["prompt_version"] = "phase8-v2"
    changed_config = ExperimentPlan.model_validate(changed_config_payload)

    dataset_identity = make_trial_identity(
        changed_dataset, changed_dataset.cells[0], _scenario(), 0
    )
    config_identity = make_trial_identity(changed_config, changed_config.cells[0], _scenario(), 0)
    scenario_identity = make_trial_identity(
        plan,
        plan.cells[0],
        _scenario(scenario_version="1.0.1"),
        0,
    )

    assert baseline.trial_id != dataset_identity.trial_id
    assert baseline.trial_id != config_identity.trial_id
    assert baseline.trial_id != scenario_identity.trial_id
    assert baseline.configuration_hash != config_identity.configuration_hash


def test_trial_identity_rejects_cross_split_scenario() -> None:
    plan = build_phase8_plans()[0]
    scenario = ScenarioRef(
        scenario_id="ops-v1-001",
        split=ExperimentSplit.DEV,
        difficulty=Difficulty.EASY,
    )

    with pytest.raises(ValueError, match="not plan split"):
        make_trial_identity(plan, plan.cells[0], scenario, 0)


def test_public_scenario_reference_has_no_ground_truth_field() -> None:
    fields = set(ScenarioRef.model_fields)

    assert "ground_truth" not in fields
    assert "expected_root_cause" not in fields
    assert "expected_primary_root_cause_code" not in fields
