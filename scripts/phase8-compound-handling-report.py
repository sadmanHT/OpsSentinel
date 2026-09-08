from __future__ import annotations

import json
import os
from pathlib import Path

from researchlab.compound_handling import (
    COMPOUND_SCENARIO_IDS,
    STOPPING_STRATEGIES,
    build_compound_handling_report,
)
from researchlab.models import StoppingStrategy, TrialRecord

STANDARD_PATH = Path(
    os.environ.get(
        "PHASE8_COMPOUND_STANDARD_INPUT",
        "phase8-compound-confidence_threshold.json",
    )
)
UNRESOLVED_PATH = Path(
    os.environ.get(
        "PHASE8_COMPOUND_UNRESOLVED_INPUT",
        "phase8-compound-unresolved_evidence.json",
    )
)
OUTPUT_PATH = Path(
    os.environ.get(
        "PHASE8_COMPOUND_REPORT_OUTPUT",
        "phase8-compound-handling-report.json",
    )
)


def _load_arm(path: Path, expected: StoppingStrategy) -> tuple[str, list[TrialRecord]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"H5 arm artifact {path} is malformed")
    if payload.get("experiment") != "compound_handling":
        raise ValueError(f"H5 arm artifact {path} has the wrong experiment")
    if payload.get("stopping_strategy") != expected.value:
        raise ValueError(f"H5 arm artifact {path} has the wrong stopping strategy")
    if payload.get("scenario_ids") != list(COMPOUND_SCENARIO_IDS):
        raise ValueError(f"H5 arm artifact {path} changed the frozen scenario cohort")
    benchmark_version = payload.get("benchmark_version")
    if not isinstance(benchmark_version, str):
        raise TypeError(f"H5 arm artifact {path} has no benchmark version")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise TypeError(f"H5 arm artifact {path} has malformed records")
    records = [TrialRecord.model_validate(item) for item in raw_records]
    if len(records) != len(COMPOUND_SCENARIO_IDS):
        raise ValueError(f"H5 arm artifact {path} must contain exactly eight records")
    return benchmark_version, records


def main() -> None:
    standard_version, standard_records = _load_arm(
        STANDARD_PATH,
        StoppingStrategy.CONFIDENCE_THRESHOLD,
    )
    unresolved_version, unresolved_records = _load_arm(
        UNRESOLVED_PATH,
        StoppingStrategy.UNRESOLVED_EVIDENCE,
    )
    if standard_version != unresolved_version:
        raise ValueError("H5 treatment arms used different benchmark versions")
    if tuple(STOPPING_STRATEGIES) != (
        StoppingStrategy.CONFIDENCE_THRESHOLD,
        StoppingStrategy.UNRESOLVED_EVIDENCE,
    ):
        raise ValueError("H5 stopping strategy order changed")
    report = build_compound_handling_report(
        benchmark_version=standard_version,
        records=standard_records + unresolved_records,
    )
    OUTPUT_PATH.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    print(
        "Phase 8 H5 report complete:",
        "observations=",
        len(report.observations),
        "pairs=",
        len(report.paired_deltas),
    )


if __name__ == "__main__":
    main()
