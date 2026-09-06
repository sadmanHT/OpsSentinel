from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
from typing import Any, cast

from pydantic import Field, model_validator

from evaluationlab.metrics import canonical_root_cause
from evaluationlab.models import StrictModel


class CounterfactualObservation(StrictModel):
    family: str = Field(min_length=1, max_length=120)
    variant: str = Field(min_length=1, max_length=120)
    expected_root_cause_codes: list[str] = Field(min_length=1)
    predicted_root_cause_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_codes(self) -> CounterfactualObservation:
        if len(self.expected_root_cause_codes) != len(set(self.expected_root_cause_codes)):
            raise ValueError("expected root-cause codes must be unique")
        if len(self.predicted_root_cause_codes) != len(set(self.predicted_root_cause_codes)):
            raise ValueError("predicted root-cause codes must be unique")
        return self


class CounterfactualPairResult(StrictModel):
    left_variant: str
    right_variant: str
    expected_changed: bool
    prediction_changed: bool
    consistent: bool


class CounterfactualMetrics(StrictModel):
    family: str
    variant_count: int = Field(ge=2)
    pair_count: int = Field(ge=1)
    consistency: float = Field(ge=0.0, le=1.0)
    causal_sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    causal_invariance: float | None = Field(default=None, ge=0.0, le=1.0)
    pairs: list[CounterfactualPairResult] = Field(min_length=1)


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _required_string(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return cast(list[str], value)


def adapt_counterfactual_observation(
    scenario: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> CounterfactualObservation:
    """Adapt one saved Phase 6 counterfactual scenario/run pair for family scoring."""
    scenario_id = _required_string(scenario, "scenario_id", "scenario")
    artifact_scenario_id = _required_string(artifact, "scenario_id", "artifact")
    if scenario_id != artifact_scenario_id:
        raise ValueError("scenario and artifact scenario_id values must match")
    if scenario.get("kind") != "counterfactual":
        raise ValueError("counterfactual scoring requires a counterfactual scenario")

    structure = _dict(scenario.get("structure"), "scenario.structure")
    family = _required_string(structure, "counterfactual_family", "scenario.structure")
    variant = _required_string(structure, "counterfactual_variant", "scenario.structure")
    ground_truth = _dict(scenario.get("ground_truth"), "scenario.ground_truth")
    expected = [
        _required_string(
            ground_truth,
            "primary_root_cause_code",
            "scenario.ground_truth",
        ),
        *_string_list(
            ground_truth.get("secondary_root_cause_codes", []),
            "scenario.ground_truth.secondary_root_cause_codes",
        ),
    ]

    raw_run = _dict(artifact.get("raw_agent_run", {}), "artifact.raw_agent_run")
    final_value = raw_run.get("final_diagnosis")
    final_diagnosis = None if final_value is None else _dict(final_value, "final_diagnosis")
    predicted_primary = _optional_string(artifact, "diagnosis_code")
    if predicted_primary is None and final_diagnosis is not None:
        predicted_primary = _optional_string(final_diagnosis, "primary_root_cause")
    predicted_secondary = (
        []
        if final_diagnosis is None
        else _string_list(
            final_diagnosis.get("secondary_root_causes", []),
            "final_diagnosis.secondary_root_causes",
        )
    )
    predicted = [] if predicted_primary is None else [predicted_primary]
    predicted.extend(code for code in predicted_secondary if code not in predicted)

    return CounterfactualObservation(
        family=family,
        variant=variant,
        expected_root_cause_codes=expected,
        predicted_root_cause_codes=predicted,
    )


def _canonical_set(codes: list[str]) -> frozenset[str]:
    normalized = {
        item
        for code in codes
        if (item := canonical_root_cause(code)) is not None
    }
    return frozenset(normalized)


def score_counterfactual_consistency(
    observations: list[CounterfactualObservation],
) -> CounterfactualMetrics:
    if len(observations) < 2:
        raise ValueError("at least two counterfactual observations are required")
    families = {item.family for item in observations}
    if len(families) != 1:
        raise ValueError("counterfactual observations must belong to one family")
    variants = [item.variant for item in observations]
    if len(variants) != len(set(variants)):
        raise ValueError("counterfactual variants must be unique within a family")

    pair_results: list[CounterfactualPairResult] = []
    changed_pairs = 0
    changed_consistent = 0
    unchanged_pairs = 0
    unchanged_consistent = 0

    ordered = sorted(observations, key=lambda item: item.variant)
    for left, right in combinations(ordered, 2):
        expected_changed = _canonical_set(left.expected_root_cause_codes) != _canonical_set(
            right.expected_root_cause_codes
        )
        prediction_changed = _canonical_set(left.predicted_root_cause_codes) != _canonical_set(
            right.predicted_root_cause_codes
        )
        consistent = expected_changed == prediction_changed
        pair_results.append(
            CounterfactualPairResult(
                left_variant=left.variant,
                right_variant=right.variant,
                expected_changed=expected_changed,
                prediction_changed=prediction_changed,
                consistent=consistent,
            )
        )
        if expected_changed:
            changed_pairs += 1
            changed_consistent += int(prediction_changed)
        else:
            unchanged_pairs += 1
            unchanged_consistent += int(not prediction_changed)

    consistent_pairs = sum(item.consistent for item in pair_results)
    return CounterfactualMetrics(
        family=next(iter(families)),
        variant_count=len(observations),
        pair_count=len(pair_results),
        consistency=consistent_pairs / len(pair_results),
        causal_sensitivity=changed_consistent / changed_pairs if changed_pairs else None,
        causal_invariance=unchanged_consistent / unchanged_pairs if unchanged_pairs else None,
        pairs=pair_results,
    )
