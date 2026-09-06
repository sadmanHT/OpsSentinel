from __future__ import annotations

import pytest
from pydantic import ValidationError

from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    ExperimentCell,
    ExperimentKind,
    ExperimentPlan,
    ExperimentSplit,
    ResearchConfiguration,
)
from researchlab.plans import build_phase8_plans


def test_phase8_catalog_defines_all_six_controlled_experiments() -> None:
    plans = build_phase8_plans()

    assert [plan.experiment for plan in plans] == list(ExperimentKind)
    assert [len(plan.cells) for plan in plans] == [2, 4, 4, 2, 2, 2]
    assert [cell.configuration.tool_budget for cell in plans[1].cells] == [5, 10, 15, 20]


def test_compound_experiment_targets_only_compound_incidents() -> None:
    compound = build_phase8_plans()[-1]

    assert all(cell.difficulties == [Difficulty.COMPOUND] for cell in compound.cells)


def test_planning_experiment_covers_every_difficulty_tier() -> None:
    planning = build_phase8_plans()[0]

    expected = set(Difficulty)
    assert all(set(cell.difficulties) == expected for cell in planning.cells)


def test_controlled_plan_rejects_configuration_contamination() -> None:
    baseline = ResearchConfiguration()
    with pytest.raises(ValidationError, match="may vary only architecture"):
        ExperimentPlan(
            id="bad-planning",
            experiment=ExperimentKind.PLANNING_DIFFICULTY,
            hypothesis_id="H1",
            dataset_version="ops-v1",
            split=ExperimentSplit.VALIDATION,
            cells=[
                ExperimentCell(
                    id="reactive",
                    label="Reactive",
                    configuration=baseline.model_copy(
                        update={"architecture": ArchitectureVariant.REACTIVE_REACT}
                    ),
                    difficulties=[Difficulty.EASY],
                ),
                ExperimentCell(
                    id="planner",
                    label="Planner",
                    configuration=baseline.model_copy(
                        update={
                            "architecture": ArchitectureVariant.EXPLICIT_PLANNER,
                            "tool_budget": 20,
                        }
                    ),
                    difficulties=[Difficulty.EASY],
                ),
            ],
        )


def test_controlled_plan_requires_target_dimension_to_actually_change() -> None:
    baseline = ResearchConfiguration()
    with pytest.raises(ValidationError, match="distinct architecture"):
        ExperimentPlan(
            id="bad-no-change",
            experiment=ExperimentKind.PLANNING_DIFFICULTY,
            hypothesis_id="H1",
            dataset_version="ops-v1",
            split=ExperimentSplit.VALIDATION,
            cells=[
                ExperimentCell(
                    id="a",
                    label="A",
                    configuration=baseline,
                    difficulties=[Difficulty.EASY],
                ),
                ExperimentCell(
                    id="b",
                    label="B",
                    configuration=baseline,
                    difficulties=[Difficulty.EASY],
                ),
            ],
        )
