from __future__ import annotations

import pytest

from benchmarklab.final_report import (
    assert_runtime_truth_isolation,
    mean_or_none,
    nearest_rank_percentile,
    rate_or_none,
    sanitize_benchmark_artifact,
)


def test_release_report_math_preserves_missing_values() -> None:
    assert mean_or_none([]) is None
    assert rate_or_none(0, 0) is None
    assert mean_or_none([0.0, 2.0]) == 1.0
    assert rate_or_none(1, 4) == 0.25
    assert nearest_rank_percentile([1.0, 2.0, 3.0, 4.0], 50.0) == 2.0
    assert nearest_rank_percentile([1.0, 2.0, 3.0, 4.0], 95.0) == 4.0


def test_sanitizer_removes_evaluator_only_labels() -> None:
    safe = sanitize_benchmark_artifact(
        {
            "scenario_id": "ops-v1-example",
            "expected_primary_root_cause_code": "SECRET",
            "expected_secondary_root_cause_codes": ["SECRET_TWO"],
            "raw_agent_run": {"incident": {"title": "public"}},
        }
    )
    assert "expected_primary_root_cause_code" not in safe
    assert "expected_secondary_root_cause_codes" not in safe


def test_runtime_truth_isolation_fails_closed() -> None:
    with pytest.raises(ValueError, match="hidden evaluator key"):
        assert_runtime_truth_isolation({"nested": {"ground_truth": "forbidden"}})
