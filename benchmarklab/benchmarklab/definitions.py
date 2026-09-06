from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from benchmarklab.models import BenchmarkCatalog, ScenarioSpec

RCA = {
    "n_plus_one": "n_plus_one_query",
    "connection_leak": "database_connection_leak",
    "disk_exhaustion": "disk_exhaustion",
    "broken_config": "broken_payment_configuration",
    "memory_leak": "memory_leak",
}
FAULTS: dict[str, dict[str, Any]] = {
    "n_plus_one": {
        "service": "checkout",
        "configuration": {"delay_per_query_ms": 3},
        "stimulus": ("checkout", "GET", "/orders", 1, 200),
        "evidence": ["metric:p95_latency", "metric:db_query_count"],
    },
    "connection_leak": {
        "service": "inventory",
        "configuration": {"capacity": 4},
        "stimulus": ("inventory", "GET", "/inventory/SKU-RED", 4, 503),
        "evidence": ["metric:db_connections", "log:inventory_503"],
    },
    "disk_exhaustion": {
        "service": "worker",
        "configuration": {"max_files": 4},
        "stimulus": ("worker", "POST", "/work", 4, 507),
        "evidence": ["metric:disk_usage", "log:worker_507"],
    },
    "broken_config": {
        "service": "payment",
        "configuration": {},
        "stimulus": ("payment", "POST", "/charge", 1, 401),
        "evidence": ["log:payment_401", "log:gateway_502"],
    },
    "memory_leak": {
        "service": "worker",
        "configuration": {"chunk_bytes": 262_144, "max_bytes": 1_048_576},
        "stimulus": ("worker", "POST", "/work", 4, 503),
        "evidence": ["metric:memory_usage", "metric:container_restarts"],
    },
}
ORDER = tuple(FAULTS)
RELEASE_TIMESTAMP = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _id(index: int) -> str:
    return f"ops-v1-{index:03d}"


def _time(index: int) -> str:
    value = datetime(2026, 2, 1, 9, 0, tzinfo=UTC) + timedelta(days=index - 1)
    return value.isoformat()


def _fault(kind: str, seed: int, offset: float) -> dict[str, Any]:
    meta = FAULTS[kind]
    return {
        "fault": kind,
        "service": meta["service"],
        "severity": "P2",
        "seed": seed,
        "configuration": dict(meta["configuration"]),
        "offset_seconds": offset,
    }


def _stimulus(kind: str, offset: float) -> dict[str, Any]:
    service, method, path, count, status = FAULTS[kind]["stimulus"]
    return {
        "service": service,
        "method": method,
        "path": path,
        "count": count,
        "expected_status": status,
        "offset_seconds": offset,
    }


def _single(
    index: int,
    *,
    difficulty: str,
    split: str,
    kind: str,
    fault: str,
    structure: str,
    template: str,
    cause: float,
    effect: float,
    distractor: str | None = None,
    counterfactual_family: str | None = None,
    counterfactual_variant: str | None = None,
) -> dict[str, Any]:
    scenario_id = _id(index)
    service = FAULTS[fault]["service"]
    timeline: list[dict[str, Any]] = []
    tags: list[str] = []
    if distractor:
        tags.append(distractor)
        timeline.append(
            {
                "event_id": "distractor",
                "offset_seconds": 0.0,
                "role": "distractor",
                "summary": "A prominent but non-causal operational change appears first.",
                "root_cause_code": None,
            }
        )
    timeline.extend(
        [
            {
                "event_id": "cause",
                "offset_seconds": cause,
                "role": "cause",
                "summary": "A hidden causal condition begins.",
                "root_cause_code": RCA[fault],
            },
            {
                "event_id": "effect",
                "offset_seconds": effect,
                "role": "effect",
                "summary": "User-visible symptoms begin.",
                "root_cause_code": RCA[fault],
            },
        ]
    )
    return {
        "scenario_id": scenario_id,
        "scenario_version": "1.0.0",
        "difficulty": difficulty,
        "split": split,
        "kind": kind,
        "seed": 10_000 + index,
        "public_incident": {
            "title": f"{service.title()} service incident {index}",
            "description": (
                "User-visible degradation is reproducible while surrounding telemetry "
                "contains only the evidence available to an investigator."
            ),
            "severity": "P2",
            "service": service,
            "start_time": _time(index),
            "scenario_id": scenario_id,
        },
        "structure": {
            "failure_structure": structure,
            "template_family": template,
            "combination_family": None,
            "counterfactual_family": counterfactual_family,
            "counterfactual_variant": counterfactual_variant,
        },
        "faults": [_fault(fault, 20_000 + index, cause)],
        "stimuli": [_stimulus(fault, effect)],
        "timeline": timeline,
        "ground_truth": {
            "primary_root_cause_code": RCA[fault],
            "secondary_root_cause_codes": [],
            "causal_attribution": "The hidden injected condition causes the observed incident.",
            "critical_evidence_tags": list(FAULTS[fault]["evidence"]),
        },
        "distractor_tags": tags,
        "budget": {
            "max_steps": 24 if difficulty in {"hard", "adversarial"} else 20,
            "max_tool_calls": 18 if difficulty in {"hard", "adversarial"} else 15,
            "time_limit_seconds": 180.0 if difficulty in {"hard", "adversarial"} else 120.0,
        },
    }


def _no_fault_counterfactual(index: int) -> dict[str, Any]:
    scenario_id = _id(index)
    return {
        "scenario_id": scenario_id,
        "scenario_version": "1.0.0",
        "difficulty": "adversarial",
        "split": "validation",
        "kind": "counterfactual",
        "seed": 10_000 + index,
        "public_incident": {
            "title": "Control window remains healthy after a visible release",
            "description": "A release occurs, but the scheduled trigger is disabled and no failure follows.",
            "severity": "P2",
            "service": "inventory",
            "start_time": _time(index),
            "scenario_id": scenario_id,
        },
        "structure": {
            "failure_structure": "validation_counterfactual_controls",
            "template_family": "validation_deploy_cron_controls",
            "combination_family": None,
            "counterfactual_family": "deploy-cron-latency",
            "counterfactual_variant": "deploy_cron_disabled",
        },
        "faults": [],
        "stimuli": [],
        "timeline": [
            {
                "event_id": "distractor",
                "offset_seconds": 0.0,
                "role": "distractor",
                "summary": "A deployment completes successfully.",
                "root_cause_code": None,
            },
            {
                "event_id": "effect",
                "offset_seconds": 120.0,
                "role": "effect",
                "summary": "The control observation remains healthy.",
                "root_cause_code": "no_fault",
            },
        ],
        "ground_truth": {
            "primary_root_cause_code": "no_fault",
            "secondary_root_cause_codes": [],
            "causal_attribution": "No benchmark fault is active in this controlled variant.",
            "critical_evidence_tags": ["metric:healthy_baseline", "log:no_errors"],
        },
        "distractor_tags": ["recent_deployment"],
        "budget": {"max_steps": 20, "max_tool_calls": 15, "time_limit_seconds": 120.0},
    }


def _compound(index: int, primary: str, secondary: str) -> dict[str, Any]:
    scenario_id = _id(index)
    primary_cause = 21_600.0 + (index - 43) * 30.0
    effect = primary_cause + 300.0
    return {
        "scenario_id": scenario_id,
        "scenario_version": "1.0.0",
        "difficulty": "compound",
        "split": "hidden_test",
        "kind": "compound",
        "seed": 10_000 + index,
        "public_incident": {
            "title": f"Acute {FAULTS[primary]['service']} incident overlaps older degradation",
            "description": (
                "Two genuine problems coexist; one explains the acute onset while another "
                "started hours earlier."
            ),
            "severity": "P1",
            "service": FAULTS[primary]["service"],
            "start_time": _time(index),
            "scenario_id": scenario_id,
        },
        "structure": {
            "failure_structure": "hidden_dual_failure_primary_secondary",
            "template_family": "hidden_compound_temporal_attribution",
            "combination_family": f"{primary}+{secondary}",
            "counterfactual_family": None,
            "counterfactual_variant": None,
        },
        "faults": [
            _fault(secondary, 30_000 + index, 0.0),
            _fault(primary, 40_000 + index, primary_cause),
        ],
        "stimuli": [_stimulus(secondary, 10_800.0), _stimulus(primary, effect)],
        "timeline": [
            {
                "event_id": "secondary_cause",
                "offset_seconds": 0.0,
                "role": "cause",
                "summary": "A genuine secondary issue begins and slowly develops.",
                "root_cause_code": RCA[secondary],
            },
            {
                "event_id": "primary_cause",
                "offset_seconds": primary_cause,
                "role": "cause",
                "summary": "The acute primary failure begins.",
                "root_cause_code": RCA[primary],
            },
            {
                "event_id": "effect",
                "offset_seconds": effect,
                "role": "effect",
                "summary": "The acute user-visible incident begins.",
                "root_cause_code": RCA[primary],
            },
        ],
        "ground_truth": {
            "primary_root_cause_code": RCA[primary],
            "secondary_root_cause_codes": [RCA[secondary]],
            "causal_attribution": (
                "The later fault is the primary acute cause; the earlier fault is genuine "
                "but secondary."
            ),
            "critical_evidence_tags": [*FAULTS[primary]["evidence"], *FAULTS[secondary]["evidence"]],
        },
        "distractor_tags": ["dual_failure_overlap"],
        "budget": {"max_steps": 30, "max_tool_calls": 24, "time_limit_seconds": 240.0},
    }


def build_release_catalog() -> BenchmarkCatalog:
    raw: list[dict[str, Any]] = []
    index = 1

    # Easy: 10 development scenarios, two strong-signal variants per fault.
    for fault in ORDER:
        for variant in range(2):
            raw.append(
                _single(
                    index,
                    difficulty="easy",
                    split="dev",
                    kind="standard",
                    fault=fault,
                    structure="dev_single_strong_signal",
                    template=f"dev_direct_{fault}_{variant}",
                    cause=0.0,
                    effect=30.0,
                )
            )
            index += 1

    # Medium: 10 development + 2 validation, each with realistic distractors.
    for offset in range(12):
        split = "dev" if offset < 10 else "validation"
        fault = ORDER[offset % len(ORDER)]
        raw.append(
            _single(
                index,
                difficulty="medium",
                split=split,
                kind="standard",
                fault=fault,
                structure=f"{split}_single_noisy_dependency",
                template=f"{split}_noisy_{fault}_{offset}",
                cause=15.0,
                effect=90.0,
                distractor="recent_change",
            )
        )
        index += 1

    # Hard: 10 development delayed/multi-service cases + two validation counterfactuals.
    for offset in range(10):
        fault = ORDER[offset % len(ORDER)]
        raw.append(
            _single(
                index,
                difficulty="hard",
                split="dev",
                kind="temporal",
                fault=fault,
                structure="dev_delayed_multiservice_signal",
                template=f"dev_delayed_{fault}_{offset}",
                cause=600.0 + offset * 30.0,
                effect=1_200.0 + offset * 30.0,
            )
        )
        index += 1
    for variant, cause, effect in (
        ("original", 0.0, 60.0),
        ("gap_then_cron", 6_420.0, 6_480.0),
    ):
        raw.append(
            _single(
                index,
                difficulty="hard",
                split="validation",
                kind="counterfactual",
                fault="connection_leak",
                structure="validation_counterfactual_timing",
                template=f"validation_cf_{variant}",
                cause=cause,
                effect=effect,
                counterfactual_family="deploy-cron-latency",
                counterfactual_variant=variant,
            )
        )
        index += 1

    # Adversarial: six validation scenarios and two structurally hidden scenarios.
    for offset in range(4):
        fault = ORDER[offset]
        raw.append(
            _single(
                index,
                difficulty="adversarial",
                split="validation",
                kind="adversarial",
                fault=fault,
                structure="validation_misleading_change_correlation",
                template=f"validation_false_lead_{fault}",
                cause=420.0,
                effect=480.0,
                distractor="misleading_deployment",
            )
        )
        index += 1
    raw.append(
        _single(
            index,
            difficulty="adversarial",
            split="validation",
            kind="counterfactual",
            fault="connection_leak",
            structure="validation_counterfactual_controls",
            template="validation_cf_no_deploy",
            cause=600.0,
            effect=660.0,
            distractor="traffic_spike",
            counterfactual_family="deploy-cron-latency",
            counterfactual_variant="no_deploy_cron",
        )
    )
    index += 1
    raw.append(_no_fault_counterfactual(index))
    index += 1
    for fault in ("connection_leak", "memory_leak"):
        raw.append(
            _single(
                index,
                difficulty="adversarial",
                split="hidden_test",
                kind="adversarial",
                fault=fault,
                structure="hidden_cron_triggered_cause",
                template=f"hidden_temporal_false_lead_{fault}",
                cause=10_800.0,
                effect=11_100.0,
                distractor="misleading_deployment",
            )
        )
        index += 1

    # Compound: eight hidden structural combinations.
    pairs = [
        ("n_plus_one", "memory_leak"),
        ("broken_config", "memory_leak"),
        ("connection_leak", "disk_exhaustion"),
        ("n_plus_one", "connection_leak"),
        ("disk_exhaustion", "memory_leak"),
        ("broken_config", "disk_exhaustion"),
        ("connection_leak", "memory_leak"),
        ("n_plus_one", "disk_exhaustion"),
    ]
    for primary, secondary in pairs:
        raw.append(_compound(index, primary, secondary))
        index += 1

    scenarios = [ScenarioSpec.model_validate(item) for item in raw]
    return BenchmarkCatalog(
        benchmark_version="1.0.0",
        generated_at=RELEASE_TIMESTAMP,
        scenarios=scenarios,
    )
