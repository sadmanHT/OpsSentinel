from __future__ import annotations

import argparse
import json
from pathlib import Path

from researchlab.models import ToolOrderVariant, TrialRecord
from researchlab.tool_order import (
    ORDERING_VARIANTS,
    TOOL_ORDER_SCENARIO_IDS,
    build_tool_order_report,
)


def _load(path: Path) -> tuple[str, ToolOrderVariant, list[TrialRecord]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"Tool Order arm artifact {path} is malformed")
    benchmark_version = payload.get("benchmark_version")
    tool_order = payload.get("tool_order")
    records = payload.get("records")
    if not isinstance(benchmark_version, str) or not isinstance(tool_order, str):
        raise TypeError(f"Tool Order arm artifact {path} is missing provenance")
    if not isinstance(records, list):
        raise TypeError(f"Tool Order arm artifact {path} is missing records")
    return (
        benchmark_version,
        ToolOrderVariant(tool_order),
        [TrialRecord.model_validate(record) for record in records],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arms", nargs=4, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    loaded = [_load(path) for path in args.arms]
    versions = {item[0] for item in loaded}
    variants = {item[1] for item in loaded}
    if len(versions) != 1:
        raise ValueError("Tool Order arms use different benchmark versions")
    if variants != set(ORDERING_VARIANTS):
        raise ValueError("Tool Order report requires exactly the four preregistered arms")

    records = [record for _, _, arm_records in loaded for record in arm_records]
    report = build_tool_order_report(
        benchmark_version=next(iter(versions)),
        records=records,
    )
    if report.scenario_ids != list(TOOL_ORDER_SCENARIO_IDS):
        raise ValueError("Tool Order report cohort differs from preregistration")

    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    print("Phase 8 Tool Order descriptive report:")
    for aggregate in report.aggregates:
        print(aggregate.model_dump(mode="json"))
    print("Phase 8 Tool Order paired deltas versus free order:")
    for delta in report.paired_deltas:
        print(delta.model_dump(mode="json"))


if __name__ == "__main__":
    main()
