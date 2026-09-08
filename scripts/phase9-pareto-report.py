from __future__ import annotations

import argparse
from pathlib import Path

from researchlab.pareto_campaign import (
    PARETO_CONFIGURATIONS,
    build_pareto_campaign_report,
    render_pareto_svg,
)
from researchlab.pareto_live import ParetoArmArtifact, validate_pareto_arm


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Phase 9 Pareto optimization report")
    parser.add_argument("arms", nargs="+", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("phase9-pareto-report.json"),
    )
    parser.add_argument(
        "--svg",
        type=Path,
        default=Path("phase9-pareto-frontier.svg"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    expected_ids = {configuration.id for configuration in PARETO_CONFIGURATIONS}
    if len(args.arms) != len(expected_ids):
        raise ValueError(
            f"Phase 9 Pareto report requires {len(expected_ids)} arm artifacts; "
            f"found {len(args.arms)}"
        )

    artifacts = [
        validate_pareto_arm(ParetoArmArtifact.model_validate_json(path.read_text()))
        for path in args.arms
    ]
    observed_ids = [artifact.configuration.id for artifact in artifacts]
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError("Phase 9 Pareto report received duplicate configuration arms")
    if set(observed_ids) != expected_ids:
        raise ValueError(
            "Phase 9 Pareto report does not contain the frozen configuration grid"
        )

    versions = {artifact.benchmark_version for artifact in artifacts}
    if len(versions) != 1:
        raise ValueError("Phase 9 Pareto arms use inconsistent benchmark versions")
    benchmark_version = versions.pop()

    trials = [trial for artifact in artifacts for trial in artifact.trials]
    report = build_pareto_campaign_report(
        benchmark_version=benchmark_version,
        trials=trials,
    )
    args.output.write_text(report.model_dump_json(indent=2) + "\n")
    args.svg.write_text(render_pareto_svg(report))
    print(
        "Phase 9 Pareto report complete:",
        "trials=",
        report.trial_count,
        "frontier=",
        ",".join(report.pareto.frontier_configuration_ids),
        "cost_basis=",
        report.pareto.cost_basis.value,
    )


if __name__ == "__main__":
    main()
