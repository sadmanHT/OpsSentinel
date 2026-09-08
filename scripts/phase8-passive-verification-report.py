from __future__ import annotations

import argparse
import json
from pathlib import Path

from researchlab.models import EvidenceMode, TrialRecord
from researchlab.passive_verification import (
    EVIDENCE_MODES,
    PASSIVE_VERIFICATION_SCENARIO_IDS,
    build_passive_verification_report,
)


def _load(path: Path) -> tuple[str, EvidenceMode, list[TrialRecord]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"H4 arm artifact {path} is malformed")
    benchmark_version = payload.get("benchmark_version")
    evidence_mode = payload.get("evidence_mode")
    records = payload.get("records")
    if not isinstance(benchmark_version, str) or not isinstance(evidence_mode, str):
        raise TypeError(f"H4 arm artifact {path} is missing provenance")
    if not isinstance(records, list):
        raise TypeError(f"H4 arm artifact {path} is missing records")
    return (
        benchmark_version,
        EvidenceMode(evidence_mode),
        [TrialRecord.model_validate(record) for record in records],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arms", nargs=2, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    loaded = [_load(path) for path in args.arms]
    versions = {item[0] for item in loaded}
    modes = {item[1] for item in loaded}
    if len(versions) != 1:
        raise ValueError("H4 arms use different benchmark versions")
    if modes != set(EVIDENCE_MODES):
        raise ValueError("H4 report requires exactly passive and verification arms")

    records = [record for _, _, arm_records in loaded for record in arm_records]
    report = build_passive_verification_report(
        benchmark_version=next(iter(versions)),
        records=records,
    )
    if report.scenario_ids != list(PASSIVE_VERIFICATION_SCENARIO_IDS):
        raise ValueError("H4 report cohort differs from preregistration")

    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    print("Phase 8 H4 descriptive report:")
    for aggregate in report.aggregates:
        print(aggregate.model_dump(mode="json"))
    print("Phase 8 H4 paired deltas, verification minus passive:")
    for delta in report.paired_deltas:
        print(delta.model_dump(mode="json"))


if __name__ == "__main__":
    main()
