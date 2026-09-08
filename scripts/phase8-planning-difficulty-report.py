from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarklab.catalog import load_catalog
from researchlab.models import ArchitectureVariant, Difficulty, TrialRecord
from researchlab.planning_difficulty import (
    SELECTION_POLICY_VERSION,
    build_planning_difficulty_report,
    select_planning_difficulty_scenarios,
)


def _load_arm(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"{path} did not contain a JSON object")
    return payload


def _record_list(payload: dict[str, Any], path: Path) -> list[TrialRecord]:
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise TypeError(f"{path} is missing a records list")
    return [TrialRecord.model_validate(record) for record in raw_records]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arms", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if len(args.arms) != 2:
        raise ValueError("planning/difficulty aggregation requires exactly two architecture arms")

    catalog = load_catalog()
    selected = select_planning_difficulty_scenarios(catalog, per_tier=2)
    expected_selected = {
        difficulty.value: [scenario.scenario_id for scenario in selected[difficulty]]
        for difficulty in Difficulty
    }

    records: list[TrialRecord] = []
    architectures: set[ArchitectureVariant] = set()
    for path in args.arms:
        payload = _load_arm(path)
        if payload.get("experiment") != "planning_difficulty":
            raise ValueError(f"{path} has the wrong experiment")
        if payload.get("hypothesis_id") != "H1":
            raise ValueError(f"{path} has the wrong hypothesis")
        if payload.get("interpretation") != "descriptive_only":
            raise ValueError(f"{path} is not marked descriptive_only")
        if payload.get("selection_policy") != SELECTION_POLICY_VERSION:
            raise ValueError(f"{path} uses a different scenario selection policy")
        if payload.get("benchmark_version") != catalog.benchmark_version:
            raise ValueError(f"{path} uses a different benchmark version")
        if payload.get("per_tier") != 2:
            raise ValueError(f"{path} uses a different per-tier sample size")
        if payload.get("selected_scenarios") != expected_selected:
            raise ValueError(f"{path} does not match the preregistered scenario selection")

        architecture_raw = payload.get("architecture")
        if not isinstance(architecture_raw, str):
            raise TypeError(f"{path} is missing architecture metadata")
        architecture = ArchitectureVariant(architecture_raw)
        architectures.add(architecture)
        arm_records = _record_list(payload, path)
        if len(arm_records) != 10:
            raise ValueError(f"{path} must contain exactly 10 completed trials")
        if any(record.identity.configuration.architecture != architecture for record in arm_records):
            raise ValueError(f"{path} contains records from a different architecture")
        records.extend(arm_records)

    if architectures != set(ArchitectureVariant):
        raise ValueError("planning/difficulty aggregation requires reactive and planner arms")
    if len({record.identity.trial_id for record in records}) != 20:
        raise ValueError("planning/difficulty trial identities are not unique")

    report = build_planning_difficulty_report(
        benchmark_version=catalog.benchmark_version,
        selected=selected,
        records=records,
        per_tier=2,
    )
    args.output.write_text(report.model_dump_json(indent=2) + "\n")

    print("Phase 8 planning/difficulty descriptive report:")
    for aggregate in report.aggregates:
        print(
            aggregate.difficulty.value,
            aggregate.architecture.value,
            "n=",
            aggregate.n,
            "accuracy=",
            aggregate.mean_root_cause_accuracy,
            "exact_match=",
            aggregate.exact_match_rate,
            "tool_calls=",
            aggregate.mean_tool_calls,
            "latency_seconds=",
            aggregate.mean_latency_seconds,
            "estimated_cost=",
            aggregate.mean_estimated_cost,
            "failures=",
            aggregate.failure_mode_counts,
        )
    print("Planner-minus-reactive deltas:")
    for delta in report.deltas:
        print(delta.model_dump(mode="json"))


if __name__ == "__main__":
    main()
