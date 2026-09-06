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

FAULT_DEFAULTS: dict[str, tuple[str, dict[str, Any]]] = {
    "n_plus_one": ("checkout", {"delay_per_query_ms": 3}),
    "connection_leak": ("inventory", {"capacity": 4}),
    "disk_exhaustion": ("worker", {"max_files": 4}),
    "broken_config": ("payment", {}),
    "memory_leak": (
        "worker",
        {"chunk_bytes": 262_144, "max_bytes": 1_048_576},
    ),
}

CRITICAL_EVIDENCE = {
    "n_plus_one": [
        "metric:p95_latency",
        "metric:db_query_count",
        "log:checkout_orders",
    ],
    "connection_leak": ["metric:db_connections", "log:inventory_503"],
    "disk_exhaustion": ["metric:disk_usage", "log:worker_507"],
    "broken_config": ["log:payment_401", "log:gateway_502"],
    "memory_leak": [
        "metric:memory_usage",
        "metric:container_restarts",
        "log:worker_503",
    ],
}


def _timestamp(index: int, *, hour: int = 9) -> str:
    base = datetime(2026, 2, 1, hour, 0, tzinfo=UTC)
    return (base + timedelta(days=index - 1)).isoformat().replace("+00:00", "Z")


def _scenario_id(index: int) -> str:
    return f"ops-v1-{index:03d}"


def _fault(
    kind: str,
    seed: int,
    *,
    offset: float = 0.0,
    severity: str = "P2",
    service: str | None = None,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default_service, default_configuration = FAULT_DEFAULTS[kind]
    return {
        "fault": kind,
        "service": service or default_service,
        "severity": severity,
        "seed": seed,
        "configuration": (
            default_configuration.copy()
            if configuration is None
            else configuration.copy()
        ),
        "offset_seconds": float(offset),
    }


def _stimuli(kind: str, *, offset: float = 0.0) -> list[dict[str, Any]]:
    if kind == "n_plus_one":
        specs = [("checkout", "GET", "/orders", 1, 200)]
    elif kind == "connection_leak":
        specs = [("inventory", "GET", "/inventory/SKU-RED", 4, 503)]
    elif kind == "disk_exhaustion":
        specs = [("worker", "POST", "/work", 4, 507)]
    elif kind == "broken_config":
        specs = [
            ("payment", "POST", "/charge", 1, 401),
            ("gateway", "GET", "/checkout", 1, 502),
        ]
    elif kind == "memory_leak":
        specs = [("worker", "POST", "/work", 4, 503)]
    else:
        raise ValueError(f"unsupported benchmark fault {kind!r}")
    return [
        {
            "service": service,
            "method": method,
            "path": path,
            "count": count,
            "expected_status": status,
            "offset_seconds": float(offset),
        }
        for service, method, path, count, status in specs
    ]


def _single(
    index: int,
    *,
    difficulty: str,
    split: str,
    kind: str,
    fault_kind: str,
    title: str,
    description: str,
    family: str,
    structure: str,
    seed: int,
    severity: str = "P2",
    cause_offset: float = 0.0,
    effect_offset: float = 60.0,
    distractors: list[str] | None = None,
    max_steps: int = 20,
    max_tool_calls: int = 15,
    time_limit_seconds: float = 120.0,
) -> dict[str, Any]:
    scenario_id = _scenario_id(index)
    service = FAULT_DEFAULTS[fault_kind][0]
    return {
        "scenario_id": scenario_id,
        "scenario_version": "1.0.0",
        "difficulty": difficulty,
        "split": split,
        "kind": kind,
        "seed": seed,
        "public_incident": {
            "title": title,
            "description": description,
            "severity": severity,
            "service": service,
            "start_time": _timestamp(index),
            "scenario_id": scenario_id,
        },
        "structure": {
            "failure_structure": structure,
            "template_family": family,
            "combination_family": None,
        },
        "faults": [
            _fault(
                fault_kind,
                seed,
                offset=cause_offset,
                severity=severity,
            )
        ],
        "stimuli": _stimuli(fault_kind, offset=effect_offset),
        "timeline": [
            {
                "event_id": "cause",
                "offset_seconds": float(cause_offset),
                "role": "cause",
                "summary": "The hidden causal condition begins in the simulator.",
                "root_cause_code": RCA[fault_kind],
            },
            {
                "event_id": "effect",
                "offset_seconds": float(effect_offset),
                "role": "effect",
                "summary": "User-visible incident symptoms become observable.",
                "root_cause_code": RCA[fault_kind],
            },
        ],
        "ground_truth": {
            "primary_root_cause_code": RCA[fault_kind],
            "secondary_root_cause_codes": [],
            "causal_attribution": (
                "The injected hidden condition is the primary cause of the observed "
                "incident symptoms."
            ),
            "critical_evidence_tags": CRITICAL_EVIDENCE[fault_kind],
        },
        "distractor_tags": distractors or [],
        "budget": {
            "max_steps": max_steps,
            "max_tool_calls": max_tool_calls,
            "time_limit_seconds": time_limit_seconds,
        },
    }


def _easy_scenarios(start: int) -> list[dict[str, Any]]:
    texts = {
        "n_plus_one": [
            (
                "Checkout requests suddenly take much longer",
                "Order-list requests are slow while still returning successful responses.",
            ),
            (
                "Order browsing latency increased",
                "Checkout latency rises sharply during ordinary order retrieval traffic.",
            ),
        ],
        "connection_leak": [
            (
                "Inventory becomes intermittently unavailable",
                "Repeated inventory lookups eventually return service errors.",
            ),
            (
                "Inventory reliability degrades under light traffic",
                "A short sequence of ordinary item lookups ends in availability failures.",
            ),
        ],
        "disk_exhaustion": [
            (
                "Worker jobs fail with storage errors",
                "Repeated job processing eventually cannot persist additional output.",
            ),
            (
                "Background processing stops accepting output",
                "Worker requests begin failing after several successful output-producing jobs.",
            ),
        ],
        "broken_config": [
            (
                "Payment authentication failures break checkout",
                "The payment dependency rejects charge attempts and checkout returns an "
                "upstream error.",
            ),
            (
                "Checkout cannot complete payment requests",
                "Payment calls are rejected while the gateway reports a dependency failure.",
            ),
        ],
        "memory_leak": [
            (
                "Worker restarts after sustained resource growth",
                "Repeated worker jobs show increasing resource pressure followed by "
                "service failure.",
            ),
            (
                "Background worker degrades across repeated jobs",
                "A short run of jobs ends with a worker failure after resource use grows.",
            ),
        ],
    }
    scenarios: list[dict[str, Any]] = []
    index = start
    for fault_kind in (
        "n_plus_one",
        "connection_leak",
        "disk_exhaustion",
        "broken_config",
        "memory_leak",
    ):
        for variant, (title, description) in enumerate(texts[fault_kind], start=1):
            scenarios.append(
                _single(
                    index,
                    difficulty="easy",
                    split="dev",
                    kind="standard",
                    fault_kind=fault_kind,
                    title=title,
                    description=description,
                    family=f"dev-easy-{fault_kind}",
                    structure=f"dev-easy-{fault_kind}-single",
                    seed=100 + index,
                    cause_offset=0,
                    effect_offset=20 + variant * 5,
                )
            )
            index += 1
    return scenarios


def _medium_scenarios(start: int) -> list[dict[str, Any]]:
    specs = [
        (
            "n_plus_one",
            "Latency regression noticed after a routine release",
            "A recent release is visible in deployment history, but the incident must be "
            "diagnosed from runtime evidence.",
            "release_context",
        ),
        (
            "n_plus_one",
            "Checkout is slow only on order-heavy requests",
            "Successful responses hide a large latency increase concentrated in order "
            "retrieval.",
            "success_status",
        ),
        (
            "connection_leak",
            "Inventory errors appear only after several healthy requests",
            "The service starts healthy, then ordinary lookups progressively become "
            "unavailable.",
            "delayed_failure",
        ),
        (
            "connection_leak",
            "Inventory saturation follows a quiet traffic period",
            "A small burst after an otherwise quiet period is enough to trigger repeated "
            "availability failures.",
            "traffic_shift",
        ),
        (
            "disk_exhaustion",
            "Worker failures follow a successful processing burst",
            "Several jobs complete before storage-related symptoms surface in later "
            "requests.",
            "delayed_storage",
        ),
        (
            "disk_exhaustion",
            "Worker health endpoint remains responsive while jobs fail",
            "Control-plane health remains reachable even though job processing cannot "
            "persist output.",
            "health_distractor",
        ),
        (
            "broken_config",
            "Gateway failures coincide with a routine deployment",
            "A deployment appears near the incident window, while payment-side evidence "
            "must establish the cause.",
            "deployment_distractor",
        ),
        (
            "broken_config",
            "Payment errors are isolated from inventory traffic",
            "Inventory remains healthy while checkout failures originate at the payment "
            "boundary.",
            "healthy_neighbor",
        ),
        (
            "memory_leak",
            "Worker degradation accumulates over repeated jobs",
            "No single request explains the failure; resource pressure grows across a "
            "sequence of jobs.",
            "accumulation",
        ),
        (
            "memory_leak",
            "Worker restarts after a normal traffic pattern",
            "Ordinary job traffic eventually causes a restart while unrelated services "
            "remain healthy.",
            "healthy_neighbors",
        ),
        (
            "n_plus_one",
            "Checkout latency rises without an error-rate spike",
            "Error status remains low even though successful requests become substantially "
            "slower.",
            "no_error_spike",
        ),
        (
            "connection_leak",
            "Inventory failures persist after successful early lookups",
            "Early request success is a distractor; later evidence shows the service can "
            "no longer serve ordinary reads.",
            "early_success",
        ),
    ]
    scenarios: list[dict[str, Any]] = []
    for offset, (fault_kind, title, description, tag) in enumerate(specs):
        index = start + offset
        scenario = _single(
            index,
            difficulty="medium",
            split="dev",
            kind="temporal" if offset % 3 == 0 else "standard",
            fault_kind=fault_kind,
            title=title,
            description=description,
            family=f"dev-medium-{fault_kind}-{tag}",
            structure=f"dev-medium-{fault_kind}-{tag}",
            seed=200 + index,
            cause_offset=30,
            effect_offset=90,
            distractors=[tag],
        )
        if "deployment" in tag or "release" in tag:
            scenario["timeline"].insert(
                0,
                {
                    "event_id": "routine_release",
                    "offset_seconds": 0.0,
                    "role": "distractor",
                    "summary": "A routine deployment is visible before the incident.",
                    "root_cause_code": None,
                },
            )
        scenarios.append(scenario)
    return scenarios


def _hard_scenarios(start: int) -> list[dict[str, Any]]:
    dev_specs = [
        (
            "n_plus_one",
            "Checkout slowdown has multiple plausible signals",
            "A routine release and healthy status codes compete with a severe latency "
            "regression.",
            "release_and_status",
        ),
        (
            "connection_leak",
            "Inventory failures emerge after noisy healthy traffic",
            "Many successful early requests precede a sharp loss of availability.",
            "noisy_prefix",
        ),
        (
            "disk_exhaustion",
            "Worker jobs fail while resource signals disagree",
            "The worker remains reachable and some system signals look normal while job "
            "output fails.",
            "mixed_signals",
        ),
        (
            "broken_config",
            "Checkout errors appear after unrelated code activity",
            "Repository activity is recent, but the failure must be localized using "
            "service-boundary evidence.",
            "code_distractor",
        ),
        (
            "memory_leak",
            "Worker failure is preceded by long resource growth",
            "The incident develops gradually and must be distinguished from transient "
            "load pressure.",
            "gradual_pressure",
        ),
        (
            "n_plus_one",
            "Checkout latency rises with unrelated deployment context",
            "Deployment history is salient, but causal evidence must come from request "
            "and database behavior.",
            "salient_deploy",
        ),
        (
            "connection_leak",
            "Inventory availability collapses after sparse symptoms",
            "Only a few late requests expose the failure after an otherwise unremarkable "
            "period.",
            "sparse_evidence",
        ),
        (
            "memory_leak",
            "Worker restart follows apparently ordinary processing",
            "The final restart is obvious, while the causal resource trend must be "
            "reconstructed from earlier evidence.",
            "restart_anchor",
        ),
    ]
    validation_specs = [
        (
            "n_plus_one",
            "Checkout latency spike begins after a quiet interval",
            "The incident has little error-rate signal and must be explained using request "
            "and database evidence.",
            "quiet_latency",
        ),
        (
            "disk_exhaustion",
            "Worker output failures appear after mixed successful jobs",
            "Some jobs succeed immediately before the incident, making the onset boundary "
            "ambiguous.",
            "boundary_ambiguity",
        ),
        (
            "broken_config",
            "Payment rejects requests while gateway symptoms dominate",
            "The user-visible gateway failure is stronger than the downstream payment clue.",
            "upstream_dominance",
        ),
        (
            "memory_leak",
            "Worker restart occurs after a long symptom-free period",
            "Resource growth predates the final outage by a substantial interval.",
            "long_horizon",
        ),
    ]
    scenarios: list[dict[str, Any]] = []
    index = start
    for fault_kind, title, description, tag in dev_specs:
        scenario = _single(
            index,
            difficulty="hard",
            split="dev",
            kind="temporal",
            fault_kind=fault_kind,
            title=title,
            description=description,
            family=f"hard-dev-{tag}",
            structure=f"hard-dev-{fault_kind}-{tag}",
            seed=300 + index,
            severity="P1",
            cause_offset=120,
            effect_offset=300,
            distractors=[tag],
            max_steps=24,
            max_tool_calls=18,
            time_limit_seconds=150.0,
        )
        scenario["timeline"].insert(
            0,
            {
                "event_id": "context",
                "offset_seconds": 30.0,
                "role": "distractor",
                "summary": "A non-causal operational event appears in the incident window.",
                "root_cause_code": None,
            },
        )
        scenarios.append(scenario)
        index += 1
    for fault_kind, title, description, tag in validation_specs:
        scenarios.append(
            _single(
                index,
                difficulty="hard",
                split="validation",
                kind="temporal",
                fault_kind=fault_kind,
                title=title,
                description=description,
                family=f"hard-val-{tag}",
                structure=f"hard-val-{fault_kind}-{tag}",
                seed=400 + index,
                severity="P1",
                cause_offset=60,
                effect_offset=420,
                distractors=[tag],
                max_steps=26,
                max_tool_calls=20,
                time_limit_seconds=180.0,
            )
        )
        index += 1
    return scenarios


def _counterfactual_negative(index: int, family: str) -> dict[str, Any]:
    scenario_id = _scenario_id(index)
    return {
        "scenario_id": scenario_id,
        "scenario_version": "1.0.0",
        "difficulty": "adversarial",
        "split": "validation",
        "kind": "counterfactual",
        "seed": 600 + index,
        "public_incident": {
            "title": "Post-release control remains healthy",
            "description": (
                "A routine release occurs while the scheduled trigger is disabled; service "
                "latency and availability remain within baseline."
            ),
            "severity": "P2",
            "service": "checkout",
            "start_time": _timestamp(index),
            "scenario_id": scenario_id,
        },
        "structure": {
            "failure_structure": "cf-val-trigger-disabled",
            "template_family": family,
            "combination_family": family,
        },
        "faults": [],
        "stimuli": [
            {
                "service": "gateway",
                "method": "GET",
                "path": "/checkout",
                "count": 1,
                "expected_status": 200,
                "offset_seconds": 420.0,
            }
        ],
        "timeline": [
            {
                "event_id": "deployment",
                "offset_seconds": 0.0,
                "role": "context",
                "summary": "A routine deployment occurs.",
                "root_cause_code": None,
            },
            {
                "event_id": "trigger_disabled",
                "offset_seconds": 300.0,
                "role": "context",
                "summary": "The scheduled trigger remains disabled.",
                "root_cause_code": None,
            },
            {
                "event_id": "healthy_control",
                "offset_seconds": 420.0,
                "role": "effect",
                "summary": "The service remains within the expected healthy baseline.",
                "root_cause_code": "no_fault",
            },
        ],
        "ground_truth": {
            "primary_root_cause_code": "no_fault",
            "secondary_root_cause_codes": [],
            "causal_attribution": (
                "With the causal trigger disabled, the deployment alone does not produce "
                "the incident effect."
            ),
            "critical_evidence_tags": ["baseline:healthy", "counterfactual:no_trigger"],
        },
        "distractor_tags": ["counterfactual_negative_control"],
        "budget": {
            "max_steps": 20,
            "max_tool_calls": 15,
            "time_limit_seconds": 120.0,
        },
    }


def _adversarial_scenarios(start: int) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    index = start

    misleading = _single(
        index,
        difficulty="adversarial",
        split="validation",
        kind="adversarial",
        fault_kind="connection_leak",
        title="Inventory outage follows an unrelated deployment",
        description=(
            "A routine release happened well before failures; later runtime evidence must "
            "determine what actually caused the outage."
        ),
        family="adv-val-misleading-deployment",
        structure="adv-val-connection-misleading-deployment",
        seed=500 + index,
        severity="P1",
        cause_offset=6_540,
        effect_offset=6_600,
        distractors=["misleading_deployment"],
        max_steps=28,
        max_tool_calls=20,
        time_limit_seconds=180.0,
    )
    misleading["public_incident"]["start_time"] = _timestamp(index, hour=22)
    misleading["timeline"] = [
        {
            "event_id": "deployment",
            "offset_seconds": 0.0,
            "role": "distractor",
            "summary": "A routine deployment occurs at 22:00.",
            "root_cause_code": None,
        },
        {
            "event_id": "scheduled_work",
            "offset_seconds": 6_420.0,
            "role": "context",
            "summary": "A scheduled workload begins at 23:47.",
            "root_cause_code": None,
        },
        {
            "event_id": "pool_saturation",
            "offset_seconds": 6_540.0,
            "role": "cause",
            "summary": "Database pool saturation begins at 23:49.",
            "root_cause_code": RCA["connection_leak"],
        },
        {
            "event_id": "api_failures",
            "offset_seconds": 6_600.0,
            "role": "effect",
            "summary": "Inventory API failures begin at 23:50.",
            "root_cause_code": RCA["connection_leak"],
        },
    ]
    scenarios.append(misleading)
    index += 1

    salient_release = _single(
        index,
        difficulty="adversarial",
        split="validation",
        kind="adversarial",
        fault_kind="n_plus_one",
        title="Checkout slowdown is reported beside a noisy release signal",
        description=(
            "A deployment is highly salient in the incident window, but only causal runtime "
            "evidence should determine attribution."
        ),
        family="adv-val-salient-release",
        structure="adv-val-checkout-salient-release",
        seed=500 + index,
        severity="P1",
        cause_offset=120,
        effect_offset=150,
        distractors=["salient_release"],
        max_steps=28,
        max_tool_calls=20,
        time_limit_seconds=180.0,
    )
    salient_release["timeline"].insert(
        0,
        {
            "event_id": "deployment",
            "offset_seconds": 0.0,
            "role": "distractor",
            "summary": "A deployment is visible but is not sufficient causal evidence.",
            "root_cause_code": None,
        },
    )
    scenarios.append(salient_release)
    index += 1

    family = "cf-val-deployment-trigger-family"
    original = _single(
        index,
        difficulty="adversarial",
        split="validation",
        kind="counterfactual",
        fault_kind="n_plus_one",
        title="Checkout slows immediately after a release",
        description=(
            "A release and the first severe latency symptoms are nearly simultaneous; "
            "attribution should follow corroborating runtime evidence."
        ),
        family=family,
        structure="cf-val-original-immediate",
        seed=600 + index,
        severity="P1",
        cause_offset=10,
        effect_offset=20,
        distractors=["counterfactual_original"],
    )
    original["structure"]["combination_family"] = family
    original["timeline"].insert(
        0,
        {
            "event_id": "deployment",
            "offset_seconds": 0.0,
            "role": "context",
            "summary": "A deployment precedes the causal runtime change.",
            "root_cause_code": None,
        },
    )
    scenarios.append(original)
    index += 1

    delayed = _single(
        index,
        difficulty="adversarial",
        split="validation",
        kind="counterfactual",
        fault_kind="connection_leak",
        title="Inventory failures begin hours after a routine release",
        description=(
            "A release occurred much earlier; a later scheduled workload precedes the first "
            "availability failures."
        ),
        family=family,
        structure="cf-val-delayed-trigger",
        seed=600 + index,
        severity="P1",
        cause_offset=7_200,
        effect_offset=7_320,
        distractors=["counterfactual_delayed"],
    )
    delayed["structure"]["combination_family"] = family
    delayed["timeline"].insert(
        0,
        {
            "event_id": "deployment",
            "offset_seconds": 0.0,
            "role": "distractor",
            "summary": "A deployment occurs two hours before the causal trigger.",
            "root_cause_code": None,
        },
    )
    delayed["timeline"].insert(
        1,
        {
            "event_id": "scheduled_work",
            "offset_seconds": 7_140.0,
            "role": "context",
            "summary": "A scheduled workload starts shortly before saturation.",
            "root_cause_code": None,
        },
    )
    scenarios.append(delayed)
    index += 1

    no_deployment = _single(
        index,
        difficulty="adversarial",
        split="validation",
        kind="counterfactual",
        fault_kind="connection_leak",
        title="Inventory failures begin during a scheduled workload",
        description=(
            "No recent release is present; a scheduled workload immediately precedes the "
            "availability failures."
        ),
        family=family,
        structure="cf-val-no-deployment-trigger",
        seed=600 + index,
        severity="P1",
        cause_offset=300,
        effect_offset=420,
        distractors=["counterfactual_no_deploy"],
    )
    no_deployment["structure"]["combination_family"] = family
    no_deployment["timeline"].insert(
        0,
        {
            "event_id": "scheduled_work",
            "offset_seconds": 240.0,
            "role": "context",
            "summary": "A scheduled workload begins before the causal condition.",
            "root_cause_code": None,
        },
    )
    scenarios.append(no_deployment)
    index += 1

    scenarios.append(_counterfactual_negative(index, family))
    index += 1

    hidden_specs = [
        (
            "broken_config",
            "Gateway symptoms point toward the wrong service",
            "The visible failure is at checkout, while only downstream evidence can "
            "localize the incident cause.",
            "wrong_service_anchor",
        ),
        (
            "memory_leak",
            "A recent worker restart is a tempting final-event explanation",
            "The restart is an effect; diagnosis must reconstruct the resource trend that "
            "preceded it.",
            "effect_as_cause",
        ),
    ]
    for fault_kind, title, description, tag in hidden_specs:
        scenarios.append(
            _single(
                index,
                difficulty="adversarial",
                split="hidden_test",
                kind="adversarial",
                fault_kind=fault_kind,
                title=title,
                description=description,
                family=f"adv-hidden-{tag}",
                structure=f"adv-hidden-{fault_kind}-{tag}",
                seed=700 + index,
                severity="P1",
                cause_offset=120,
                effect_offset=480,
                distractors=[tag],
                max_steps=28,
                max_tool_calls=20,
                time_limit_seconds=180.0,
            )
        )
        index += 1
    return scenarios


def _compound_scenario(
    index: int,
    *,
    primary_fault: str,
    secondary_fault: str,
    title: str,
    description: str,
    tag: str,
    primary_service: str | None = None,
    primary_stimulus: list[dict[str, Any]] | None = None,
    flagship: bool = False,
) -> dict[str, Any]:
    scenario_id = _scenario_id(index)
    seed = 800 + index
    primary_code = RCA[primary_fault]
    secondary_code = RCA[secondary_fault]
    if flagship:
        secondary_offset = 0.0
        secondary_signal = 18_000.0
        primary_offset = 19_500.0
        effect_offset = 19_800.0
    else:
        secondary_offset = 0.0
        secondary_signal = 120.0
        primary_offset = 300.0
        effect_offset = 360.0

    primary_default_service = FAULT_DEFAULTS[primary_fault][0]
    primary_target = primary_service or primary_default_service
    faults = [
        _fault(secondary_fault, seed + 1, offset=secondary_offset, severity="P2"),
        _fault(
            primary_fault,
            seed,
            offset=primary_offset,
            severity="P1",
            service=primary_target,
        ),
    ]
    stimuli = _stimuli(secondary_fault, offset=secondary_signal)
    stimuli.extend(
        primary_stimulus
        if primary_stimulus is not None
        else _stimuli(primary_fault, offset=effect_offset)
    )
    timeline = [
        {
            "event_id": "secondary_cause",
            "offset_seconds": secondary_offset,
            "role": "cause",
            "summary": "A pre-existing secondary condition begins.",
            "root_cause_code": secondary_code,
        },
        {
            "event_id": "secondary_signal",
            "offset_seconds": secondary_signal,
            "role": "context",
            "summary": "Evidence of the secondary condition becomes observable.",
            "root_cause_code": secondary_code,
        },
    ]
    if flagship:
        timeline.append(
            {
                "event_id": "checkout_deployment",
                "offset_seconds": 19_500.0,
                "role": "context",
                "summary": "A checkout deployment occurs at 14:25.",
                "root_cause_code": None,
            }
        )
    timeline.extend(
        [
            {
                "event_id": "primary_cause",
                "offset_seconds": primary_offset,
                "role": "cause",
                "summary": "The acute primary condition begins later.",
                "root_cause_code": primary_code,
            },
            {
                "event_id": "acute_effect",
                "offset_seconds": effect_offset,
                "role": "effect",
                "summary": "The primary user-visible incident becomes acute.",
                "root_cause_code": primary_code,
            },
        ]
    )
    return {
        "scenario_id": scenario_id,
        "scenario_version": "1.0.0",
        "difficulty": "compound",
        "split": "hidden_test",
        "kind": "compound",
        "seed": seed,
        "public_incident": {
            "title": title,
            "description": description,
            "severity": "P1",
            "service": primary_target,
            "start_time": _timestamp(index),
            "scenario_id": scenario_id,
        },
        "structure": {
            "failure_structure": f"compound-hidden-{tag}",
            "template_family": f"compound-hidden-{tag}",
            "combination_family": (
                "compound-hidden-" + "+".join(sorted([primary_fault, secondary_fault]))
            ),
        },
        "faults": faults,
        "stimuli": stimuli,
        "timeline": timeline,
        "ground_truth": {
            "primary_root_cause_code": primary_code,
            "secondary_root_cause_codes": [secondary_code],
            "causal_attribution": (
                "The primary condition explains the acute incident; the secondary "
                "condition is independent and pre-existing."
            ),
            "critical_evidence_tags": (
                CRITICAL_EVIDENCE[primary_fault] + CRITICAL_EVIDENCE[secondary_fault]
            ),
        },
        "distractor_tags": ["compound", "premature_convergence_risk"],
        "budget": {
            "max_steps": 30,
            "max_tool_calls": 22,
            "time_limit_seconds": 180.0,
        },
    }


def _compound_scenarios(start: int) -> list[dict[str, Any]]:
    specs = [
        (
            "n_plus_one",
            "memory_leak",
            "Checkout latency spikes while an older worker resource issue also exists",
            "Checkout becomes acutely slow after a recent change, while a separate worker "
            "degradation began much earlier.",
            "flagship-acute-vs-preexisting",
        ),
        (
            "connection_leak",
            "memory_leak",
            "Inventory availability collapses while worker health is also degrading",
            "Inventory requests begin failing acutely, while an independent worker resource "
            "trend predates the outage.",
            "inventory-plus-worker",
        ),
        (
            "n_plus_one",
            "disk_exhaustion",
            "Checkout slows while background jobs also begin failing",
            "A checkout latency incident coincides with independent worker output failures; "
            "both issues must be retained in the diagnosis.",
            "checkout-plus-storage",
        ),
        (
            "n_plus_one",
            "broken_config",
            "Checkout is slow and payment attempts also fail",
            "Two independent checkout-path symptoms coexist: severe order latency and "
            "downstream payment rejection.",
            "checkout-plus-payment",
        ),
        (
            "connection_leak",
            "disk_exhaustion",
            "Inventory fails while worker jobs cannot persist output",
            "Two services fail for independent reasons during the same incident window.",
            "inventory-plus-storage",
        ),
        (
            "broken_config",
            "memory_leak",
            "Checkout payment failures coincide with worker degradation",
            "Payment rejection is acute while a separate worker resource problem has been "
            "developing longer.",
            "payment-plus-worker",
        ),
        (
            "disk_exhaustion",
            "memory_leak",
            "Gateway requests fail while a separate worker degradation also exists",
            "Gateway traffic begins failing acutely, while an independent worker resource "
            "trend predates the outage.",
            "gateway-storage-plus-worker",
        ),
        (
            "connection_leak",
            "broken_config",
            "Inventory and payment fail in the same incident window",
            "Availability failures affect inventory while payment requests are independently "
            "rejected.",
            "inventory-plus-payment",
        ),
    ]
    scenarios: list[dict[str, Any]] = []
    for offset, spec in enumerate(specs):
        index = start + offset
        primary_fault, secondary_fault, title, description, tag = spec
        if tag == "gateway-storage-plus-worker":
            scenario = _compound_scenario(
                index,
                primary_fault=primary_fault,
                secondary_fault=secondary_fault,
                title=title,
                description=description,
                tag=tag,
                primary_service="gateway",
                primary_stimulus=[
                    {
                        "service": "gateway",
                        "method": "GET",
                        "path": "/checkout",
                        "count": 4,
                        "expected_status": 507,
                        "offset_seconds": 360.0,
                    }
                ],
            )
            scenario["ground_truth"]["critical_evidence_tags"] = [
                "metric:disk_usage",
                "log:gateway_507",
                *CRITICAL_EVIDENCE[secondary_fault],
            ]
        else:
            scenario = _compound_scenario(
                index,
                primary_fault=primary_fault,
                secondary_fault=secondary_fault,
                title=title,
                description=description,
                tag=tag,
                flagship=offset == 0,
            )
        scenarios.append(scenario)
    return scenarios


def build_catalog() -> BenchmarkCatalog:
    raw: list[dict[str, Any]] = []
    raw.extend(_easy_scenarios(1))
    raw.extend(_medium_scenarios(11))
    raw.extend(_hard_scenarios(23))
    raw.extend(_adversarial_scenarios(35))
    raw.extend(_compound_scenarios(43))
    scenarios = [ScenarioSpec.model_validate(item) for item in raw]
    return BenchmarkCatalog(
        benchmark_name="OpsSentinel BenchmarkLab",
        benchmark_version="1.0.0",
        generated_at=datetime(2026, 9, 6, tzinfo=UTC),
        scenarios=scenarios,
    )
