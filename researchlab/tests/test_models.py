from __future__ import annotations

import pytest

from researchlab.models import Difficulty, ExperimentSplit, ScenarioRef, make_trial_identity
from researchlab.plans import build_phase8_plans


def test_trial_identity_and_seed_are_deterministic() -> None:
    plan = build_phase8_plans(repeat_count=2)[0]
    cell = plan.cells[0]
    scenario = ScenarioRef(
        scenario_id="ops-v1-001",
        split=ExperimentSplit.VALIDATION,
        difficulty=Difficulty.EASY,
    )

    first = make_trial_identity(plan, cell, scenario, 0)
    replay = make_trial_identity(plan, cell, scenario, 0)
    repeated = make_trial_identity(plan, cell, scenario, 1)

    assert first == replay
    assert first.trial_id != repeated.trial_id
    assert first.seed != repeated.seed


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
