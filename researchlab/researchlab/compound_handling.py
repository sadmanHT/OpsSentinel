from __future__ import annotations

import json
from statistics import fmean

from benchmarklab.catalog import scenario_by_id
from benchmarklab.models import BenchmarkCatalog
from pydantic import BaseModel, ConfigDict, Field

from researchlab.benchmark_adapter import scenario_ref_from_benchmark
from researchlab.live_executor import (
    COMPOUND_EVIDENCE_PROVIDER_MARKER,
    UNRESOLVED_EVIDENCE_PROVIDER_MARKER,
)
from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    EvidenceMode,
    ExperimentPlan,
    ExperimentSplit,
    ScenarioRef,
    StoppingStrategy,
    TemporalReasoningVariant,
    ToolOrderVariant,
    TrialRecord,
    TrialStatus,
)
from researchlab.plans import build_phase8_plans

COMPOUND_SCENARIO_IDS = tuple(f"ops-v1-{index:03d}" for index in range(43, 51))
STOPPING_STRATEGIES = (
    StoppingStrategy.CONFIDENCE_THRESHOLD,
    StoppingStrategy.UNRESOLVED_EVIDENCE,
)
DATASET_POLICY_VERSION = "phase8-compound-hidden-cohort-v1"
EXPECTED_PLAN = (
    (
        "checkout-db-query-count",
        "query_metrics",
        {"service": "checkout", "metric": "db_query_count"},
    ),
    (
        "checkout-request-logs",
        "search_logs",
        {"service": "checkout", "query": "/orders", "limit": 20},
    ),
    (
        "inventory-db-connections",
        "query_metrics",
        {"service": "inventory", "metric": "db_connections"},
    ),
    (
        "inventory-errors",
        "search_logs",
        {"service": "inventory", "level": "ERROR", "limit": 20},
    ),
    (
        "worker-disk",
        "query_metrics",
        {"service": "worker", "metric": "disk_usage"},
    ),
    (
        "worker-memory",
        "query_metrics",
        {"service": "worker", "metric": "memory_usage"},
    ),
    (
        "worker-restarts",
        "query_metrics",
        {"service": "worker", "metric": "container_restarts"},
    ),
    (
        "worker-errors",
        "search_logs",
        {"service": "worker", "level": "ERROR", "limit": 20},
    ),
    (
        "payment-warnings",
        "search_logs",
        {"service": "payment", "level": "WARNING", "limit": 20},
    ),
    (
        "gateway-errors",
        "search_logs",
        {"service": "gateway", "level": "ERROR", "limit": 20},
    ),
)


class CompoundReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompoundObservation(CompoundReportModel):
    trial_id: str
    scenario_id: str
    stopping_strategy: StoppingStrategy
    root_cause_accuracy: float
    exact_match: float
    secondary_recall: float
    multi_root_cause_precision: float
    multi_root_cause_recall: float
    evidence_precision: float
    evidence_recall: float
    critical_evidence_recall: float
    confidence: float
    tool_calls: float
    latency_seconds: float
    estimated_cost: float
    planned_step_ids: list[str]
    completed_required_steps: int = Field(ge=0)
    required_step_count: int = Field(ge=1)
    full_plan_completed: bool
    executed_tools: list[str]


class CompoundAggregate(CompoundReportModel):
    stopping_strategy: StoppingStrategy
    n: int = Field(ge=1)
    mean_root_cause_accuracy: float
    exact_match_rate: float
    mean_secondary_recall: float
    mean_multi_root_cause_precision: float
    mean_multi_root_cause_recall: float
    mean_evidence_precision: float
    mean_evidence_recall: float
    mean_critical_evidence_recall: float
    mean_confidence: float
    mean_tool_calls: float
    mean_latency_seconds: float
    mean_estimated_cost: float
    mean_completed_required_steps: float
    full_plan_completion_rate: float = Field(ge=0.0, le=1.0)


class CompoundPairDelta(CompoundReportModel):
    scenario_id: str
    root_cause_accuracy_delta: float
    exact_match_delta: float
    secondary_recall_delta: float
    multi_root_cause_precision_delta: float
    multi_root_cause_recall_delta: float
    evidence_recall_delta: float
    tool_calls_delta: float
    latency_seconds_delta: float
    completed_required_steps_delta: int


class CompoundHandlingReport(CompoundReportModel):
    experiment: str = "compound_handling"
    interpretation: str = "descriptive_only"
    dataset_policy: str = DATASET_POLICY_VERSION
    benchmark_version: str
    scenario_ids: list[str]
    observations: list[CompoundObservation]
    aggregates: list[CompoundAggregate]
    paired_deltas: list[CompoundPairDelta]


def compound_handling_plan(
    *,
    dataset_version: str,
    provider: str = "local",
    model: str = "local-placeholder",
    prompt_version: str = "phase8-v1",
) -> ExperimentPlan:
    plans = build_phase8_plans(
        dataset_version=dataset_version,
        split=ExperimentSplit.HIDDEN_TEST,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        repeat_count=1,
    )
    plan = next(item for item in plans if item.id == "phase8-compound-handling")
    if plan.split != ExperimentSplit.HIDDEN_TEST:
        raise ValueError("H5 must use the hidden_test compound split")
    strategies = tuple(cell.configuration.stopping_strategy for cell in plan.cells)
    if strategies != STOPPING_STRATEGIES:
        raise ValueError("H5 cells do not match the preregistered stopping treatments")
    for cell in plan.cells:
        configuration = cell.configuration
        if cell.difficulties != [Difficulty.COMPOUND]:
            raise ValueError("H5 cells must contain only compound difficulty")
        if configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
            raise ValueError("H5 must hold architecture fixed at explicit_planner")
        if configuration.tool_budget != 15:
            raise ValueError("H5 must hold tool budget fixed at 15")
        if configuration.tool_order != ToolOrderVariant.FREE:
            raise ValueError("H5 must hold tool order fixed at free")
        if configuration.temporal_reasoning != TemporalReasoningVariant.STANDARD:
            raise ValueError("H5 must hold temporal reasoning fixed at standard")
        if configuration.evidence_mode != EvidenceMode.PASSIVE_ONLY:
            raise ValueError("H5 must hold evidence mode fixed at passive_only")
    return plan


def compound_handling_scenarios(catalog: BenchmarkCatalog) -> list[ScenarioRef]:
    scenarios = [scenario_by_id(catalog, scenario_id) for scenario_id in COMPOUND_SCENARIO_IDS]
    if any(scenario.split.value != ExperimentSplit.HIDDEN_TEST.value for scenario in scenarios):
        raise ValueError("H5 cohort must contain only hidden_test scenarios")
    if any(scenario.difficulty.value != Difficulty.COMPOUND.value for scenario in scenarios):
        raise ValueError("H5 cohort must contain only compound scenarios")
    if any(scenario.kind.value != "compound" for scenario in scenarios):
        raise ValueError("H5 cohort must contain only compound benchmark cases")
    return [scenario_ref_from_benchmark(scenario) for scenario in scenarios]


def _dict(record: TrialRecord, key: str) -> dict[str, object]:
    value = record.raw_trajectory.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"H5 trial {record.identity.trial_id} is missing {key}")
    return value


def _raw_agent_run(record: TrialRecord) -> dict[str, object]:
    artifact = _dict(record, "benchmark_artifact")
    raw_run = artifact.get("raw_agent_run")
    if not isinstance(raw_run, dict):
        raise ValueError("H5 benchmark artifact is missing the raw agent run")
    return raw_run


def _validate_plan(raw_run: dict[str, object]) -> tuple[list[str], int, int]:
    plan = raw_run.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("H5 raw agent run is missing its investigation plan")
    raw_steps = plan.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("H5 investigation plan has malformed steps")
    if len(raw_steps) != len(EXPECTED_PLAN):
        raise ValueError("H5 shared investigation plan length changed")
    step_ids: list[str] = []
    completed_required = 0
    required_count = 0
    for raw_step, expected in zip(raw_steps, EXPECTED_PLAN, strict=True):
        if not isinstance(raw_step, dict):
            raise ValueError("H5 investigation plan contains a malformed step")
        expected_id, expected_tool, expected_arguments = expected
        step_id = raw_step.get("id")
        tool = raw_step.get("tool")
        arguments = raw_step.get("arguments")
        if step_id != expected_id or tool != expected_tool or arguments != expected_arguments:
            raise ValueError("H5 shared investigation plan invocation changed")
        if raw_step.get("required") is not True:
            raise ValueError("H5 shared investigation plan must keep every step required")
        step_ids.append(expected_id)
        required_count += 1
        if raw_step.get("completed") is True:
            completed_required += 1
    return step_ids, completed_required, required_count


def _executed_tools(raw_run: dict[str, object]) -> list[str]:
    history = raw_run.get("tool_history", [])
    if not isinstance(history, list):
        raise ValueError("H5 raw agent run has malformed tool history")
    tools: list[str] = []
    for item in history:
        if not isinstance(item, dict):
            raise ValueError("H5 tool history contains a malformed entry")
        tool = item.get("tool_name")
        if not isinstance(tool, str):
            raise ValueError("H5 tool history entry is missing tool_name")
        tools.append(tool)
    return tools


def _assert_no_hidden_truth_leak(record: TrialRecord, raw_run: dict[str, object]) -> None:
    case = _dict(record, "evaluation_case")
    incident = json.dumps(raw_run.get("incident", {}), sort_keys=True).casefold()
    for forbidden in ("ground_truth", "timeline", "offset_seconds"):
        if forbidden in incident:
            raise ValueError(f"H5 agent incident leaked hidden benchmark field {forbidden}")
    expected_codes: list[str] = []
    primary = case.get("expected_primary_root_cause_code")
    if isinstance(primary, str):
        expected_codes.append(primary)
    secondary = case.get("expected_secondary_root_cause_codes", [])
    if isinstance(secondary, list):
        expected_codes.extend(item for item in secondary if isinstance(item, str))
    for code in expected_codes:
        if code.casefold() in incident:
            raise ValueError("H5 agent incident leaked an expected root-cause code")


def observation_from_record(record: TrialRecord) -> CompoundObservation:
    if record.status != TrialStatus.COMPLETED:
        raise ValueError("H5 reporting requires completed trials")
    if record.identity.split != ExperimentSplit.HIDDEN_TEST:
        raise ValueError("H5 reporting requires hidden_test trials")
    if record.identity.difficulty != Difficulty.COMPOUND:
        raise ValueError("H5 reporting requires compound trials")
    configuration = record.identity.configuration
    if configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
        raise ValueError("H5 reporting requires explicit_planner trials")
    health = _dict(record, "runtime_health")
    provider = health.get("provider")
    if health.get("compound_evidence_plan") is not True:
        raise ValueError("H5 runtime did not expose the shared compound evidence plan")
    if not isinstance(provider, str) or COMPOUND_EVIDENCE_PROVIDER_MARKER not in provider:
        raise ValueError("H5 runtime is missing the compound evidence provider marker")
    if health.get("stopping_strategy") != configuration.stopping_strategy.value:
        raise ValueError("H5 runtime stopping strategy does not match the trial")
    expects_unresolved = configuration.stopping_strategy == StoppingStrategy.UNRESOLVED_EVIDENCE
    if (UNRESOLVED_EVIDENCE_PROVIDER_MARKER in provider) != expects_unresolved:
        raise ValueError("H5 unresolved-evidence provider marker does not match the trial")

    raw_run = _raw_agent_run(record)
    _assert_no_hidden_truth_leak(record, raw_run)
    step_ids, completed_required, required_count = _validate_plan(raw_run)
    executed_tools = _executed_tools(raw_run)
    if len(executed_tools) > required_count:
        raise ValueError("H5 executed more tools than the frozen shared plan permits")
    if expects_unresolved:
        if completed_required != required_count:
            raise ValueError("H5 unresolved-evidence arm stopped with required evidence unresolved")
        if len(executed_tools) != required_count:
            raise ValueError("H5 unresolved-evidence arm did not execute the complete shared plan")

    required_scores = {
        "root_cause_accuracy",
        "exact_match",
        "secondary_recall",
        "multi_root_cause_precision",
        "multi_root_cause_recall",
        "evidence_precision",
        "evidence_recall",
        "critical_evidence_recall",
        "confidence",
        "tool_calls",
        "latency_seconds",
        "estimated_cost",
    }
    missing = sorted(required_scores - set(record.scores))
    if missing:
        raise ValueError(f"H5 trial is missing scores: {', '.join(missing)}")
    return CompoundObservation(
        trial_id=str(record.identity.trial_id),
        scenario_id=record.identity.scenario_id,
        stopping_strategy=configuration.stopping_strategy,
        root_cause_accuracy=record.scores["root_cause_accuracy"],
        exact_match=record.scores["exact_match"],
        secondary_recall=record.scores["secondary_recall"],
        multi_root_cause_precision=record.scores["multi_root_cause_precision"],
        multi_root_cause_recall=record.scores["multi_root_cause_recall"],
        evidence_precision=record.scores["evidence_precision"],
        evidence_recall=record.scores["evidence_recall"],
        critical_evidence_recall=record.scores["critical_evidence_recall"],
        confidence=record.scores["confidence"],
        tool_calls=record.scores["tool_calls"],
        latency_seconds=record.scores["latency_seconds"],
        estimated_cost=record.scores["estimated_cost"],
        planned_step_ids=step_ids,
        completed_required_steps=completed_required,
        required_step_count=required_count,
        full_plan_completed=completed_required == required_count,
        executed_tools=executed_tools,
    )


def _aggregate(
    observations: list[CompoundObservation],
    strategy: StoppingStrategy,
) -> CompoundAggregate:
    group = [item for item in observations if item.stopping_strategy == strategy]
    if not group:
        raise ValueError(f"H5 is missing the {strategy.value} treatment")
    return CompoundAggregate(
        stopping_strategy=strategy,
        n=len(group),
        mean_root_cause_accuracy=fmean(item.root_cause_accuracy for item in group),
        exact_match_rate=fmean(item.exact_match for item in group),
        mean_secondary_recall=fmean(item.secondary_recall for item in group),
        mean_multi_root_cause_precision=fmean(
            item.multi_root_cause_precision for item in group
        ),
        mean_multi_root_cause_recall=fmean(item.multi_root_cause_recall for item in group),
        mean_evidence_precision=fmean(item.evidence_precision for item in group),
        mean_evidence_recall=fmean(item.evidence_recall for item in group),
        mean_critical_evidence_recall=fmean(
            item.critical_evidence_recall for item in group
        ),
        mean_confidence=fmean(item.confidence for item in group),
        mean_tool_calls=fmean(item.tool_calls for item in group),
        mean_latency_seconds=fmean(item.latency_seconds for item in group),
        mean_estimated_cost=fmean(item.estimated_cost for item in group),
        mean_completed_required_steps=fmean(
            item.completed_required_steps for item in group
        ),
        full_plan_completion_rate=fmean(float(item.full_plan_completed) for item in group),
    )


def build_compound_handling_report(
    *,
    benchmark_version: str,
    records: list[TrialRecord],
) -> CompoundHandlingReport:
    observations = sorted(
        (observation_from_record(record) for record in records),
        key=lambda item: (item.scenario_id, item.stopping_strategy.value),
    )
    expected_count = len(COMPOUND_SCENARIO_IDS) * len(STOPPING_STRATEGIES)
    if len(observations) != expected_count:
        raise ValueError(f"H5 requires exactly {expected_count} completed observations")
    if len({item.trial_id for item in observations}) != expected_count:
        raise ValueError("H5 contains duplicate trial identities")
    by_key = {(item.scenario_id, item.stopping_strategy): item for item in observations}
    paired: list[CompoundPairDelta] = []
    for scenario_id in COMPOUND_SCENARIO_IDS:
        standard = by_key.get((scenario_id, StoppingStrategy.CONFIDENCE_THRESHOLD))
        unresolved = by_key.get((scenario_id, StoppingStrategy.UNRESOLVED_EVIDENCE))
        if standard is None or unresolved is None:
            raise ValueError(f"H5 is missing a treatment arm for {scenario_id}")
        if standard.planned_step_ids != unresolved.planned_step_ids:
            raise ValueError(f"H5 treatment arms changed the shared plan for {scenario_id}")
        paired.append(
            CompoundPairDelta(
                scenario_id=scenario_id,
                root_cause_accuracy_delta=(
                    unresolved.root_cause_accuracy - standard.root_cause_accuracy
                ),
                exact_match_delta=unresolved.exact_match - standard.exact_match,
                secondary_recall_delta=unresolved.secondary_recall - standard.secondary_recall,
                multi_root_cause_precision_delta=(
                    unresolved.multi_root_cause_precision
                    - standard.multi_root_cause_precision
                ),
                multi_root_cause_recall_delta=(
                    unresolved.multi_root_cause_recall - standard.multi_root_cause_recall
                ),
                evidence_recall_delta=unresolved.evidence_recall - standard.evidence_recall,
                tool_calls_delta=unresolved.tool_calls - standard.tool_calls,
                latency_seconds_delta=(
                    unresolved.latency_seconds - standard.latency_seconds
                ),
                completed_required_steps_delta=(
                    unresolved.completed_required_steps
                    - standard.completed_required_steps
                ),
            )
        )
    return CompoundHandlingReport(
        benchmark_version=benchmark_version,
        scenario_ids=list(COMPOUND_SCENARIO_IDS),
        observations=observations,
        aggregates=[_aggregate(observations, strategy) for strategy in STOPPING_STRATEGIES],
        paired_deltas=paired,
    )
