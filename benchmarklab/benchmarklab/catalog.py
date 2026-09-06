from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from benchmarklab.models import BenchmarkCatalog, ScenarioSpec
from benchmarklab.validation import validate_release_catalog


DEFAULT_CATALOG_RESOURCE = "data/scenarios-v1.json"


def load_catalog(path: str | Path | None = None, *, validate_release: bool = True) -> BenchmarkCatalog:
    if path is None:
        resource = files("benchmarklab").joinpath(DEFAULT_CATALOG_RESOURCE)
        raw = resource.read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")
    catalog = BenchmarkCatalog.model_validate(json.loads(raw))
    if validate_release:
        validate_release_catalog(catalog)
    return catalog


def scenario_by_id(catalog: BenchmarkCatalog, scenario_id: str) -> ScenarioSpec:
    for scenario in catalog.scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(f"unknown benchmark scenario {scenario_id!r}")
