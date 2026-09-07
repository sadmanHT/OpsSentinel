from __future__ import annotations

from pathlib import Path

from benchmarklab.catalog import load_catalog

from researchlab.models import ArchitectureVariant, TemporalReasoningVariant
from researchlab.temporal_reasoning import (
    H3_NEGATIVE_CONTROL,
    H3_SCENARIO_IDS,
    temporal_reasoning_plan,
    temporal_scenarios,
)


def test_h3_plan_changes_only_temporal_reasoning() -> None:
    catalog = load_catalog()
    plan = temporal_reasoning_plan(dataset_version=catalog.benchmark_version)

    assert [cell.id for cell in plan.cells] == ["standard", "explicit-cause-effect"]
    standard, explicit = plan.cells
    assert standard.configuration.architecture == ArchitectureVariant.EXPLICIT_PLANNER
    assert explicit.configuration.architecture == ArchitectureVariant.EXPLICIT_PLANNER
    assert standard.configuration.temporal_reasoning == TemporalReasoningVariant.STANDARD
    assert (
        explicit.configuration.temporal_reasoning
        == TemporalReasoningVariant.EXPLICIT_CAUSE_EFFECT
    )
    left = standard.configuration.model_dump()
    right = explicit.configuration.model_dump()
    differing = {key for key in left if left[key] != right[key]}
    assert differing == {"temporal_reasoning"}


def test_h3_cohort_is_frozen_and_contains_fault_free_negative_control() -> None:
    catalog = load_catalog()
    refs = temporal_scenarios(catalog)

    assert [item.scenario_id for item in refs] == list(H3_SCENARIO_IDS)
    assert H3_NEGATIVE_CONTROL == "ops-v1-040"
    for scenario_id in H3_SCENARIO_IDS[:4]:
        scenario = next(item for item in catalog.scenarios if item.scenario_id == scenario_id)
        assert scenario.split.value == "validation"
        assert scenario.difficulty.value == "adversarial"
        assert scenario.distractor_tags
    control = next(
        item for item in catalog.scenarios if item.scenario_id == H3_NEGATIVE_CONTROL
    )
    assert control.ground_truth.primary_root_cause_code == "no_fault"
    assert control.faults == []


def test_agent_temporal_provider_has_no_benchmark_truth_dependency() -> None:
    source_path = Path(__file__).parents[2] / "backend" / "app" / "agent" / "temporal.py"
    source = source_path.read_text().casefold()

    assert "from benchmarklab" not in source
    assert "import benchmarklab" not in source
    assert "ground_truth" not in source
    assert "offset_seconds" not in source
    assert "chaoslab" not in source
