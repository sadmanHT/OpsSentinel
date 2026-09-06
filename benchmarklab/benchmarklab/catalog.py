from __future__ import annotations

from benchmarklab.definitions import build_release_catalog
from benchmarklab.models import BenchmarkCatalog, ScenarioSpec
from benchmarklab.validation import validate_release_catalog


def load_catalog(*, validate_release: bool = True) -> BenchmarkCatalog:
    catalog = build_release_catalog()
    if validate_release:
        validate_release_catalog(catalog)
    return catalog


def scenario_by_id(catalog: BenchmarkCatalog, scenario_id: str) -> ScenarioSpec:
    for scenario in catalog.scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(f"unknown benchmark scenario {scenario_id!r}")
