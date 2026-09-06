from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from benchmarklab.models import (
    FAULT_RCA_CODES,
    LEAKAGE_ALIASES,
    BenchmarkCatalog,
    BenchmarkSplit,
    Difficulty,
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
        value = getattr(scenario.structure, key_name)
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
    forbidden = {code.casefold() for code in codes if code != "no_fault"}
    for fault in scenario.faults:
        forbidden.add(FAULT_RCA_CODES[fault.fault].casefold())
        forbidden.update(alias.casefold() for alias in LEAKAGE_ALIASES[fault.fault])
    leaked = sorted(item for item in forbidden if item and item in visible)
    if leaked:
        raise CatalogValidationError(
            f"agent-visible text for {scenario.scenario_id} leaks ground truth: {leaked}"
        )


def validate_timeline(scenario: ScenarioSpec) -> None:
    events = sorted(scenario.timeline, key=lambda item: item.offset_seconds)
    effect_offsets = [event.offset_seconds for event in events if event.role.value == "effect"]
    if not effect_offsets:
        raise CatalogValidationError(f"{scenario.scenario_id} has no effect event")
    first_effect = min(effect_offsets)
    for event in events:
        if event.role.value == "cause" and event.offset_seconds > first_effect:
            raise CatalogValidationError(
                f"{scenario.scenario_id} contains a cause after the first effect"
            )

    if scenario.difficulty == Difficulty.HARD and scenario.kind != ScenarioKind.COUNTERFACTUAL:
        cause_offsets = [
            event.offset_seconds for event in events if event.role.value == "cause"
        ]
        if cause_offsets and first_effect - min(cause_offsets) < 300:
            raise CatalogValidationError(
                f"hard scenario {scenario.scenario_id} must contain a delayed effect"
            )

    if scenario.difficulty == Difficulty.ADVERSARIAL:
        distractors = [
            event
            for event in events
            if event.role.value == "distractor" and event.offset_seconds < first_effect
        ]
        if not distractors:
            raise CatalogValidationError(
                f"adversarial scenario {scenario.scenario_id} needs a pre-effect distractor"
            )


def validate_counterfactual_family(catalog: BenchmarkCatalog) -> None:
    families: dict[str, set[str]] = defaultdict(set)
    for scenario in catalog.scenarios:
        family = scenario.structure.counterfactual_family
        variant = scenario.structure.counterfactual_variant
        if family and variant:
            families[family].add(variant)
    if not families:
        raise CatalogValidationError("release catalog requires a counterfactual family")
    if max(len(variants) for variants in families.values()) < 4:
        raise CatalogValidationError(
            "release catalog requires at least one four-variant counterfactual family"
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
    if scenario.faults and not scenario.stimuli:
        raise CatalogValidationError(
            f"{scenario.scenario_id} has injected faults but no observable stimulus"
        )
    if not scenario.ground_truth.critical_evidence_tags:
        raise CatalogValidationError(
            f"{scenario.scenario_id} must declare critical evidence tags"
        )
    if scenario.difficulty == Difficulty.MEDIUM and not scenario.distractor_tags:
        raise CatalogValidationError(
            f"medium scenario {scenario.scenario_id} requires a distractor"
        )
    if scenario.difficulty == Difficulty.ADVERSARIAL and not scenario.distractor_tags:
        raise CatalogValidationError(
            f"adversarial scenario {scenario.scenario_id} requires a distractor"
        )
    if scenario.difficulty == Difficulty.COMPOUND:
        if len(scenario.faults) < 2:
            raise CatalogValidationError(
                f"compound scenario {scenario.scenario_id} requires two faults"
            )
        if not scenario.ground_truth.secondary_root_cause_codes:
            raise CatalogValidationError(
                f"compound scenario {scenario.scenario_id} requires secondary root cause"
            )
    validate_timeline(scenario)


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
    validate_counterfactual_family(catalog)
    validate_reproducibility_metadata(catalog)
    for scenario in catalog.scenarios:
        validate_agent_payload_is_public_only(scenario)
        validate_scenario_runtime_contract(scenario)


def public_catalog_summary(catalog: BenchmarkCatalog) -> dict[str, Any]:
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
