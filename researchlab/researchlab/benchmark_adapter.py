from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from researchlab.models import Difficulty, ExperimentSplit, ScenarioRef


class EnumValue(Protocol):
    @property
    def value(self) -> str: ...


class BenchmarkScenarioMetadata(Protocol):
    @property
    def scenario_id(self) -> str: ...

    @property
    def scenario_version(self) -> str: ...

    @property
    def split(self) -> EnumValue: ...

    @property
    def difficulty(self) -> EnumValue: ...


def scenario_ref_from_benchmark(scenario: BenchmarkScenarioMetadata) -> ScenarioRef:
    """Project only non-ground-truth BenchmarkLab metadata into ResearchLab."""
    return ScenarioRef(
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        split=ExperimentSplit(scenario.split.value),
        difficulty=Difficulty(scenario.difficulty.value),
    )


def scenario_refs_from_benchmark(
    scenarios: Iterable[BenchmarkScenarioMetadata],
    *,
    split: ExperimentSplit | None = None,
) -> list[ScenarioRef]:
    refs = [scenario_ref_from_benchmark(scenario) for scenario in scenarios]
    if split is not None:
        refs = [scenario for scenario in refs if scenario.split == split]
    return sorted(refs, key=lambda scenario: scenario.scenario_id)
