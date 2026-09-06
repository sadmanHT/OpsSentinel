from __future__ import annotations

from itertools import combinations

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
        causal_sensitivity=(
            changed_consistent / changed_pairs if changed_pairs else None
        ),
        causal_invariance=(
            unchanged_consistent / unchanged_pairs if unchanged_pairs else None
        ),
        pairs=pair_results,
    )
