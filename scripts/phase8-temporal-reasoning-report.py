from __future__ import annotations

import argparse
import json
from pathlib import Path

from researchlab.models import TemporalReasoningVariant, TrialRecord
from researchlab.temporal_reasoning import (
    H3_SCENARIO_IDS,
    build_temporal_reasoning_report,
)


def _load(path: Path) -> tuple[str, TemporalReasoningVariant, list[TrialRecord]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"H3 arm artifact {path} is malformed")
    benchmark_version = payload.get("benchmark_version")
    temporal = payload.get("temporal_reasoning")
    records = payload.get("records")
    if not isinstance(benchmark_version, str) or not isinstance(temporal, str):
        raise TypeError(f"H3 arm artifact {path} is missing provenance")
    if not isinstance(records, list):
        raise TypeError(f"H3 arm artifact {path} is missing records")
    return (
        benchmark_version,
        TemporalReasoningVariant(temporal),
        [TrialRecord.model_validate(record) for record in records],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arms", nargs=2, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    loaded = [_load(path) for path in args.arms]
    versions = {item[0] for item in loaded}
    variants = {item[1] for item in loaded}
    if len(versions) != 1:
        raise ValueError("H3 arms use different benchmark versions")
    if variants != {
        TemporalReasoningVariant.STANDARD,
        TemporalReasoningVariant.EXPLICIT_CAUSE_EFFECT,
    }:
        raise ValueError("H3 report requires exactly the standard and explicit temporal arms")

    records = [record for _, _, arm_records in loaded for record in arm_records]
    report = build_temporal_reasoning_report(
        benchmark_version=next(iter(versions)),
        records=records,
    )
    if report.scenario_ids != list(H3_SCENARIO_IDS):
        raise ValueError("H3 report cohort differs from preregistration")

    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    print("Phase 8 temporal-reasoning descriptive report:")
    for aggregate in report.aggregates:
        print(aggregate.model_dump(mode="json"))
    print("Phase 8 temporal-reasoning paired deltas:")
    for delta in report.paired_deltas:
        print(delta.model_dump(mode="json"))


if __name__ == "__main__":
    main()
