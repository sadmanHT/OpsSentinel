from collections import Counter, defaultdict

from benchmarklab import load_catalog
from benchmarklab.models import BenchmarkSplit, Difficulty, ScenarioKind
from benchmarklab.validation import (
    NO_FAULT_EVIDENCE,
    RELEASE_DIFFICULTY_COUNTS,
    RELEASE_SPLIT_COUNTS,
    REQUIRED_EVIDENCE_BY_FAULT,
    validate_release_catalog,
)


def test_release_catalog_has_required_distribution() -> None:
    catalog = load_catalog()
    assert len(catalog.scenarios) == 50
    assert Counter(s.difficulty for s in catalog.scenarios) == Counter(
        RELEASE_DIFFICULTY_COUNTS
    )
    assert Counter(s.split for s in catalog.scenarios) == Counter(RELEASE_SPLIT_COUNTS)


def test_release_catalog_is_reproducible() -> None:
    first = load_catalog().model_dump(mode="json")
    second = load_catalog().model_dump(mode="json")
    assert first == second


def test_every_scenario_passes_release_validation() -> None:
    catalog = load_catalog(validate_release=False)
    validate_release_catalog(catalog)


def test_every_scenario_declares_required_primitive_evidence() -> None:
    catalog = load_catalog()
    for scenario in catalog.scenarios:
        declared = set(scenario.ground_truth.critical_evidence_tags)
        if not scenario.faults:
            assert NO_FAULT_EVIDENCE <= declared
            continue
        required: set[str] = set()
        for fault in scenario.faults:
            required.update(REQUIRED_EVIDENCE_BY_FAULT[fault.fault])
        assert required <= declared


def test_structural_families_are_held_out_by_split() -> None:
    catalog = load_catalog()
    for attribute in ("failure_structure", "template_family", "combination_family"):
        owners: dict[str, set[BenchmarkSplit]] = defaultdict(set)
        for scenario in catalog.scenarios:
            value = getattr(scenario.structure, attribute)
            if value:
                owners[value].add(scenario.split)
        assert all(len(splits) == 1 for splits in owners.values())


def test_agent_payload_exposes_only_public_incident_fields() -> None:
    catalog = load_catalog()
    allowed = {"title", "description", "severity", "service", "start_time", "scenario_id"}
    for scenario in catalog.scenarios:
        payload = scenario.agent_payload()
        assert set(payload) == allowed
        serialized = repr(payload).casefold()
        assert "ground_truth" not in serialized
        assert "primary_root_cause" not in serialized
        assert "faults" not in serialized
        assert scenario.ground_truth.primary_root_cause_code.casefold() not in serialized


def test_medium_adversarial_and_compound_contracts() -> None:
    catalog = load_catalog()
    for scenario in catalog.scenarios:
        if scenario.difficulty == Difficulty.MEDIUM:
            assert scenario.distractor_tags
        if scenario.difficulty == Difficulty.ADVERSARIAL:
            assert scenario.distractor_tags
            assert any(event.role.value == "distractor" for event in scenario.timeline)
        if scenario.difficulty == Difficulty.COMPOUND:
            assert scenario.kind == ScenarioKind.COMPOUND
            assert len(scenario.faults) >= 2
            assert scenario.ground_truth.secondary_root_cause_codes


def test_counterfactual_family_has_four_controlled_variants() -> None:
    catalog = load_catalog()
    variants = {
        scenario.structure.counterfactual_variant
        for scenario in catalog.scenarios
        if scenario.structure.counterfactual_family == "deploy-cron-latency"
    }
    assert variants == {
        "original",
        "gap_then_cron",
        "no_deploy_cron",
        "deploy_cron_disabled",
    }


def test_catalog_has_all_required_difficulty_tiers() -> None:
    catalog = load_catalog()
    assert {scenario.difficulty for scenario in catalog.scenarios} == set(Difficulty)
