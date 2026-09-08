from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any, cast

BANNED_RUNTIME_KEYS = frozenset(
    {
        "ground_truth",
        "expected_primary_root_cause_code",
        "expected_secondary_root_cause_codes",
        "fault_state",
        "causal_timeline",
    }
)


def mean_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def rate_or_none(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def nearest_rank_percentile(
    values: Sequence[float],
    percentile: float,
) -> float | None:
    if not values:
        return None
    if not 0.0 < percentile <= 100.0:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(values)
    rank = max(1, ceil((percentile / 100.0) * len(ordered)))
    return ordered[rank - 1]


def assert_runtime_truth_isolation(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.casefold() in BANNED_RUNTIME_KEYS:
                raise ValueError(f"hidden evaluator key leaked into runtime trajectory: {key}")
            assert_runtime_truth_isolation(item)
    elif isinstance(value, list):
        for item in value:
            assert_runtime_truth_isolation(item)


def sanitize_benchmark_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    safe = dict(artifact)
    safe.pop("expected_primary_root_cause_code", None)
    safe.pop("expected_secondary_root_cause_codes", None)
    raw_run = safe.get("raw_agent_run")
    if raw_run is not None:
        assert_runtime_truth_isolation(raw_run)
    return cast(dict[str, Any], safe)
