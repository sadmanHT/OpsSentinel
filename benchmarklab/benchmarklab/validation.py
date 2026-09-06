from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from benchmarklab.models import (
    BenchmarkCatalog,
    BenchmarkSplit,
    Difficulty,
    FAULT_RCA_CODES,
    LEAKAGE_ALIASES,
    ScenarioKind,
    ScenarioSpec,
)


RELEASE_DIFFICULTY_COUNTS: dict[Difficulty, int] = {
    Difficulty.EASY: 10,
    Difficulty.MEDIUM: 12,
    Difficulty.HARD: 12,
    Difficulty.ADVERSARIAL: 8,
    Difficulty.COMPOUND: 8,
}

RELEASE_SPLIT_COUNTS: dict[BenchmarkSplit, int] = {
    BenchmarkSplit.DEV: 30,
    BenchmarkSplit.VALIDATION: 10,
    BenchmarkSplit.HIDDEN_TEST: 10,
}


class CatalogValidationError(ValueError):
    pass


def _single_split_by_key(
    scenarios: Iterable[ScenarioSpec],
    *,
    key_name: str,
) -> None:
    seen: dict[str, set[BenchmarkSplit]] = defaultdict(set)
    for scenario in scenarios:
        structure = scenario.structure
        value = getattr(structure, key_name)
        if value:
            seen[str(value)].add(scenario.split)
    leaking = {key: splits for key, splits in seen.items() if len(splits) > 1}
    if leaking:
        details = ", ".join(
            f"{key}=>{sorted(split.value for split in splits)}"
            for key, splits in sorted(leaking.items())
        )
        raise CatalogValidationError(f"structural split leakage in {key_name}: {details}")


def validate_structural_holdouts(catalog: BenchmarkCatalog) -> None:
    """Ensure failure structures/templates/combinations never cross data splits."""

    for key_name in ("failure_structure", "template_family", "combination_family"):
        _single_split_by_key(catalog.scenarios, key_name=key_name)


def validate_agent_payload_is_public_only(scenario: ScenarioSpec) -> None:
    payload = scenario.agent_payload()
    allowed = {"title", "description", "severity", "service", "start_time", "scenario_id"}
    if set(payload) != allowed:
        raise CatalogValidationError(
            f"agent payload for {scenario.scenario_id} contains non-public fields: "
            f"{sorted(set(payload) - allowed)}"
        )

    visible = f"{payload['title']} {payload['description']}".casefold()
    codes = {
        scenario.ground_truth.primary_root_cause_code,
        *scenario.ground_truth.secondary_root_cause_codes,
    }
    forbidden = {code.casefold() for code in codes}
    for fault in scenario.faults:
        forbidden.add(FAULT_RCA_CODES[fault.fault].casefold())
        forbidden.update(alias.casefold() for alias in LEAKAGE_ALIASES[fault.fault])
    leaked = sorted(item for item in forbidden if item and item in visible)
    if leaked:
        raise CatalogValidationError(
            f"agent-visible text for {scenario.scenario_id} leaks ground truth: {leaked}"
        )


def validate_reproducibility_metadata(catalog: BenchmarkCatalog) -> None:
    for scenario in catalog.scenarios:
        if scenario.seed < 0:
            raise CatalogValidationError(f"negative seed in {scenario.scenario_id}")
        if any(fault.seed < 0 for fault in scenario.faults):
            raise CatalogValidationError(f"negative fault seed in {scenario.scenario_id}")
        if not scenario.scenario_version:
            raise CatalogValidationError(f"missing scenario version in {scenario.scenario_id}")


def validate_scenario_runtime_contract(scenario: ScenarioSpec) -> None:
    """Reject scenarios that cannot produce a useful simulator observation."""

    if scenario.kind != ScenarioKind.COUNTERFACTUAL or scenario.faults:
        if not scenario.stimuli:
            raise CatalogValidationError(
                f"{scenario.scenario_id} has injected faults but no observable stimulus"
            )
    if not scenario.ground_truth.critical_evidence_tags:
        raise CatalogValidationError(
            f"{scenario.scenario_id} must declare critical evidence tags"
        )


def validate_release_catalog(catalog: BenchmarkCatalog) -> None:
    if len(catalog.scenarios) != 50:
        raise CatalogValidationError(
            f"BenchmarkLab v1 requires exactly 50 scenarios, got {len(catalog.scenarios)}"
        )

    difficulty_counts = Counter(scenario.difficulty for scenario in catalog.scenarios)
    if difficulty_counts != Counter(RELEASE_DIFFICULTY_COUNTS):
        raise CatalogValidationError(
            f"difficulty distribution mismatch: {dict(difficulty_counts)}"
        )

    split_counts = Counter(scenario.split for scenario in catalog.scenarios)
    if split_counts != Counter(RELEASE_SPLIT_COUNTS):
        raise CatalogValidationError(f"split distribution mismatch: {dict(split_counts)}")

    validate_structural_holdouts(catalog)
    validate_reproducibility_metadata(catalog)
    for scenario in catalog.scenarios:
        validate_agent_payload_is_public_only(scenario)
        validate_scenario_runtime_contract(scenario)


def public_catalog_summary(catalog: BenchmarkCatalog) -> dict[str, Any]:
    """Return benchmark metadata without hidden labels or fault specifications."""

    return {
        "benchmark_name": catalog.benchmark_name,
        "benchmark_version": catalog.benchmark_version,
        "scenario_count": len(catalog.scenarios),
        "difficulty_counts": {
            difficulty.value: sum(
                scenario.difficulty == difficulty for scenario in catalog.scenarios
            )
            for difficulty in Difficulty
        },
        "split_counts": {
            split.value: sum(scenario.split == split for scenario in catalog.scenarios)
            for split in BenchmarkSplit
        },
    }
