from __future__ import annotations

from enum import StrEnum

from researchlab.benchmark_adapter import (
    scenario_ref_from_benchmark,
    scenario_refs_from_benchmark,
)
from researchlab.models import Difficulty, ExperimentSplit


class Split(StrEnum):
    DEV = "dev"
    VALIDATION = "validation"


class Tier(StrEnum):
    EASY = "easy"
    HARD = "hard"


class LeakGuardScenario:
    def __init__(
        self,
        scenario_id: str,
        scenario_version: str,
        split: Split,
        difficulty: Tier,
    ) -> None:
        self.scenario_id = scenario_id
        self.scenario_version = scenario_version
        self.split = split
        self.difficulty = difficulty

    @property
    def ground_truth(self) -> object:
        raise AssertionError("ResearchLab adapter must never read BenchmarkLab ground truth")


def test_benchmark_adapter_projects_only_safe_structural_metadata() -> None:
    source = LeakGuardScenario("ops-v1-001", "1.2.3", Split.VALIDATION, Tier.EASY)

    ref = scenario_ref_from_benchmark(source)

    assert ref.scenario_id == "ops-v1-001"
    assert ref.scenario_version == "1.2.3"
    assert ref.split == ExperimentSplit.VALIDATION
    assert ref.difficulty == Difficulty.EASY
    assert set(ref.model_dump()) == {"scenario_id", "scenario_version", "split", "difficulty"}


def test_benchmark_adapter_filters_split_without_touching_labels() -> None:
    sources = [
        LeakGuardScenario("ops-v1-002", "1.0.0", Split.DEV, Tier.HARD),
        LeakGuardScenario("ops-v1-001", "1.0.0", Split.VALIDATION, Tier.EASY),
    ]

    refs = scenario_refs_from_benchmark(sources, split=ExperimentSplit.VALIDATION)

    assert [ref.scenario_id for ref in refs] == ["ops-v1-001"]
