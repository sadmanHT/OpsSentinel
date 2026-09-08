from __future__ import annotations

import json
from collections import Counter
from statistics import fmean

from benchmarklab.catalog import scenario_by_id
from benchmarklab.models import BenchmarkCatalog
from pydantic import BaseModel, ConfigDict, Field

from researchlab.benchmark_adapter import scenario_ref_from_benchmark
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

PASSIVE_VERIFICATION_SCENARIO_IDS = (
    "ops-v1-021",
    "ops-v1-022",
    "ops-v1-033",
    "ops-v1-034",
    "ops-v1-035",
    "ops-v1-036",
    "ops-v1-037",
    "ops-v1-038",
    "ops-v1-039",
    "ops-v1-040",
)
PASSIVE_VERIFICATION_NEGATIVE_CONTROL = "ops-v1-040"
DATASET_POLICY_VERSION = "phase8-passive-verification-cohort-v1"
EVIDENCE_MODES = (
    EvidenceMode.PASSIVE_ONLY,
    EvidenceMode.VERIFICATION_ENABLED,
)
VERIFICATION_TOOLS = frozenset({"reproduce_request", "rerun_load_test"})


class PassiveVerificationReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PassiveVerificationObservation(PassiveVerificationReportModel):
    trial_id: str
    scenario_id: str
    difficulty: Difficulty
    evidence_mode: EvidenceMode
    root_cause_accuracy: float
    exact_match: float
    evidence_precision: float
    evidence_recall: float
    critical_evidence_recall: float
    confidence: float
    tool_calls: float
    latency_seconds: float
    estimated_cost: float
    false_positive: bool | None = None
    first_planned_tool: str | None = None
    planned_order: list[str]
    planned_invocations: list[str]
    executed_verification_count: int = Field(ge=0)
    executed_verification_tools: list[str]
    failure_categories: list[str] = Field(default_factory=list)


class PassiveVerificationAggregate(PassiveVerificationReportModel):
    evidence_mode: EvidenceMode
    n: int = Field(ge=1)
    mean_root_cause_accuracy: float
    exact_match_rate: float
    mean_evidence_precision: float
    mean_evidence_recall: float
    mean_critical_evidence_recall: float
    mean_confidence: float
    mean_tool_calls: float
    mean_latency_seconds: float
    mean_estimated_cost: float
    mean_executed_verification_count: float
    adversarial_n: int = Field(ge=0)
    adversarial_root_cause_accuracy: float | None = None
    adversarial_exact_match_rate: float | None = None
    negative_control_n: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    failure_mode_counts: dict[str, int]


class PassiveVerificationPairDelta(PassiveVerificationReportModel):
    scenario_id: str
    root_cause_accuracy_delta: float
    exact_match_delta: float
    evidence_precision_delta: float
    evidence_recall_delta: float
    critical_evidence_recall_delta: float
    confidence_delta: float
    tool_calls_delta: float


class PassiveVerificationReport(PassiveVerificationReportModel):
    experiment: str = "passive_vs_verification"
    interpretation: str = "descriptive_only"
    dataset_policy: str = DATASET_POLICY_VERSION
    benchmark_version: str
    scenario_ids: list[str]
    observations: list[PassiveVerificationObservation]
    aggregates: list[PassiveVerificationAggregate]
    paired_deltas: list[PassiveVerificationPairDelta]


def passive_verification_plan(
    *,
    dataset_version: str,
    provider: str = "local",
    model: str = "local-placeholder",
    prompt_version: str = "phase8-v1",
) -> ExperimentPlan:
    plans = build_phase8_plans(
        dataset_version=dataset_version,
        split=ExperimentSplit.VALIDATION,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        repeat_count=1,
    )
    plan = next(item for item in plans if item.id == "phase8-passive-verification")
    modes = tuple(cell.configuration.evidence_mode for cell in plan.cells)
    if modes != EVIDENCE_MODES:
        raise ValueError("H4 cells do not match passive and verification treatments")
    for cell in plan.cells:
        configuration = cell.configuration
        if configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
            raise ValueError("H4 must hold architecture fixed at explicit_planner")
        if configuration.tool_budget != 15:
            raise ValueError("H4 must hold tool budget fixed at 15")
        if configuration.tool_order != ToolOrderVariant.FREE:
            raise ValueError("H4 must hold tool order fixed at free")
        if configuration.temporal_reasoning != TemporalReasoningVariant.STANDARD:
            raise ValueError("H4 must hold temporal reasoning fixed at standard")
        if configuration.stopping_strategy != StoppingStrategy.CONFIDENCE_THRESHOLD:
            raise ValueError("H4 must hold stopping strategy fixed")
    return plan


def passive_verification_scenarios(catalog: BenchmarkCatalog) -> list[ScenarioRef]:
    scenarios = [
        scenario_by_id(catalog, scenario_id)
        for scenario_id in PASSIVE_VERIFICATION_SCENARIO_IDS
    ]
    if any(scenario.split.value != ExperimentSplit.VALIDATION.value for scenario in scenarios):
        raise ValueError("H4 cohort must contain only validation scenarios")
    adversarial = [
        scenario
        for scenario in scenarios
        if scenario.difficulty.value == Difficulty.ADVERSARIAL.value
    ]
    if len(adversarial) != 6:
        raise ValueError("H4 cohort must retain exactly six adversarial scenarios")
    control = scenarios[-1]
    if control.scenario_id != PASSIVE_VERIFICATION_NEGATIVE_CONTROL:
        raise ValueError("H4 negative-control identity changed")
    if control.ground_truth.primary_root_cause_code != "no_fault" or control.faults:
        raise ValueError("H4 negative control must remain fault-free with no_fault truth")
    return [scenario_ref_from_benchmark(scenario) for scenario in scenarios]


def _dict(record: TrialRecord, key: str) -> dict[str, object]:
    value = record.raw_trajectory.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"H4 trial {record.identity.trial_id} is missing {key}")
    return value


def _failure_categories(result: dict[str, object]) -> list[str]:
    raw = result.get("failure_classifications", [])
    if not isinstance(raw, list):
        return []
    values: set[str] = set()
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("category"), str):
            values.add(str(item["category"]))
    return sorted(values)


def _canonical_invocation(tool: str, arguments: dict[str, object]) -> str:
    return json.dumps(
        {"tool": tool, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _planned_invocations(raw_run: dict[str, object]) -> tuple[list[str], list[str]]:
    plan = raw_run.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("H4 raw agent run is missing its investigation plan")
    raw_steps = plan.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("H4 investigation plan contains no steps")
    order: list[str] = []
    invocations: list[str] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise ValueError("H4 investigation plan contains a malformed step")
        tool = raw_step.get("tool")
        arguments = raw_step.get("arguments")
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            raise ValueError("H4 plan step is missing tool or arguments")
        typed_arguments = {str(key): value for key, value in arguments.items()}
        order.append(tool)
        invocations.append(_canonical_invocation(tool, typed_arguments))
    if len(invocations) != len(set(invocations)):
        raise ValueError("H4 plan contains duplicate invocations")
    return order, invocations


def _executed_verification_tools(raw_run: dict[str, object]) -> list[str]:
    raw_history = raw_run.get("tool_history", [])
    if not isinstance(raw_history, list):
        raise ValueError("H4 raw agent run has malformed tool history")
    tools: list[str] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool_name")
        if isinstance(tool, str) and tool in VERIFICATION_TOOLS:
            tools.append(tool)
    return tools


def observation_from_record(record: TrialRecord) -> PassiveVerificationObservation:
    if record.status != TrialStatus.COMPLETED:
        raise ValueError("H4 reporting requires completed trials")
    configuration = record.identity.configuration
    if configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
        raise ValueError("H4 reporting requires explicit_planner trials")
    case = _dict(record, "evaluation_case")
    result = _dict(record, "evaluation_result")
    artifact = _dict(record, "benchmark_artifact")
    raw_run = artifact.get("raw_agent_run")
    if not isinstance(raw_run, dict):
        raise ValueError("H4 benchmark artifact is missing the raw agent run")
    expected = case.get("expected_primary_root_cause_code")
    predicted = case.get("predicted_primary_root_cause_code")
    false_positive: bool | None = None
    if isinstance(expected, str) and expected.casefold() == "no_fault":
        false_positive = not (
            isinstance(predicted, str) and predicted.casefold() == "no_fault"
        )
    planned_order, planned_invocations = _planned_invocations(raw_run)
    executed_verification_tools = _executed_verification_tools(raw_run)
    required = {
        "root_cause_accuracy",
        "exact_match",
        "evidence_precision",
        "evidence_recall",
        "critical_evidence_recall",
        "confidence",
        "tool_calls",
        "latency_seconds",
        "estimated_cost",
    }
    missing = sorted(required - set(record.scores))
    if missing:
        raise ValueError(f"H4 trial is missing scores: {', '.join(missing)}")
    return PassiveVerificationObservation(
        trial_id=str(record.identity.trial_id),
        scenario_id=record.identity.scenario_id,
        difficulty=record.identity.difficulty,
        evidence_mode=configuration.evidence_mode,
        root_cause_accuracy=record.scores["root_cause_accuracy"],
        exact_match=record.scores["exact_match"],
        evidence_precision=record.scores["evidence_precision"],
        evidence_recall=record.scores["evidence_recall"],
        critical_evidence_recall=record.scores["critical_evidence_recall"],
        confidence=record.scores["confidence"],
        tool_calls=record.scores["tool_calls"],
        latency_seconds=record.scores["latency_seconds"],
        estimated_cost=record.scores["estimated_cost"],
        false_positive=false_positive,
        first_planned_tool=planned_order[0] if planned_order else None,
        planned_order=planned_order,
        planned_invocations=planned_invocations,
        executed_verification_count=len(executed_verification_tools),
        executed_verification_tools=executed_verification_tools,
        failure_categories=_failure_categories(result),
    )


def _aggregate(
    observations: list[PassiveVerificationObservation],
    mode: EvidenceMode,
) -> PassiveVerificationAggregate:
    group = [item for item in observations if item.evidence_mode == mode]
    if not group:
        raise ValueError(f"H4 is missing the {mode.value} treatment")
    adversarial = [item for item in group if item.difficulty == Difficulty.ADVERSARIAL]
    controls = [item for item in group if item.false_positive is not None]
    false_positive_count = sum(bool(item.false_positive) for item in controls)
    failures = Counter(category for item in group for category in item.failure_categories)
    return PassiveVerificationAggregate(
        evidence_mode=mode,
        n=len(group),
        mean_root_cause_accuracy=fmean(item.root_cause_accuracy for item in group),
        exact_match_rate=fmean(item.exact_match for item in group),
        mean_evidence_precision=fmean(item.evidence_precision for item in group),
        mean_evidence_recall=fmean(item.evidence_recall for item in group),
        mean_critical_evidence_recall=fmean(
            item.critical_evidence_recall for item in group
        ),
        mean_confidence=fmean(item.confidence for item in group),
        mean_tool_calls=fmean(item.tool_calls for item in group),
        mean_latency_seconds=fmean(item.latency_seconds for item in group),
        mean_estimated_cost=fmean(item.estimated_cost for item in group),
        mean_executed_verification_count=fmean(
            item.executed_verification_count for item in group
        ),
        adversarial_n=len(adversarial),
        adversarial_root_cause_accuracy=(
            fmean(item.root_cause_accuracy for item in adversarial) if adversarial else None
        ),
        adversarial_exact_match_rate=(
            fmean(item.exact_match for item in adversarial) if adversarial else None
        ),
        negative_control_n=len(controls),
        false_positive_count=false_positive_count,
        false_positive_rate=(false_positive_count / len(controls) if controls else None),
        failure_mode_counts=dict(sorted(failures.items())),
    )


def _strip_verification(
    observation: PassiveVerificationObservation,
) -> list[str]:
    return [
        invocation
        for tool, invocation in zip(
            observation.planned_order,
            observation.planned_invocations,
            strict=True,
        )
        if tool not in VERIFICATION_TOOLS
    ]


def build_passive_verification_report(
    *,
    benchmark_version: str,
    records: list[TrialRecord],
) -> PassiveVerificationReport:
    observations = sorted(
        (observation_from_record(record) for record in records),
        key=lambda item: (item.scenario_id, item.evidence_mode.value),
    )
    expected_count = len(PASSIVE_VERIFICATION_SCENARIO_IDS) * len(EVIDENCE_MODES)
    if len(observations) != expected_count:
        raise ValueError(f"H4 requires exactly {expected_count} completed observations")
    if len({item.trial_id for item in observations}) != expected_count:
        raise ValueError("H4 contains duplicate trial identities")

    by_key = {(item.scenario_id, item.evidence_mode): item for item in observations}
    paired: list[PassiveVerificationPairDelta] = []
    for scenario_id in PASSIVE_VERIFICATION_SCENARIO_IDS:
        passive = by_key.get((scenario_id, EvidenceMode.PASSIVE_ONLY))
        active = by_key.get((scenario_id, EvidenceMode.VERIFICATION_ENABLED))
        if passive is None or active is None:
            raise ValueError(f"H4 is missing a treatment arm for {scenario_id}")
        passive_verification_steps = [
            tool for tool in passive.planned_order if tool in VERIFICATION_TOOLS
        ]
        active_verification_steps = [
            tool for tool in active.planned_order if tool in VERIFICATION_TOOLS
        ]
        if passive_verification_steps:
            raise ValueError(f"H4 passive arm contains a verification step for {scenario_id}")
        if len(active_verification_steps) != 1:
            raise ValueError(
                f"H4 active arm must plan exactly one verification step for {scenario_id}"
            )
        if passive.executed_verification_count != 0:
            raise ValueError(f"H4 passive arm executed verification for {scenario_id}")
        if active.executed_verification_count != 1:
            raise ValueError(
                f"H4 active arm must execute exactly one verification probe for {scenario_id}"
            )
        if passive.first_planned_tool != active.first_planned_tool:
            raise ValueError(f"H4 changed the first passive step for {scenario_id}")
        if passive.planned_invocations != _strip_verification(active):
            raise ValueError(f"H4 changed the passive planned invocation sequence for {scenario_id}")
        paired.append(
            PassiveVerificationPairDelta(
                scenario_id=scenario_id,
                root_cause_accuracy_delta=(
                    active.root_cause_accuracy - passive.root_cause_accuracy
                ),
                exact_match_delta=active.exact_match - passive.exact_match,
                evidence_precision_delta=(
                    active.evidence_precision - passive.evidence_precision
                ),
                evidence_recall_delta=active.evidence_recall - passive.evidence_recall,
                critical_evidence_recall_delta=(
                    active.critical_evidence_recall - passive.critical_evidence_recall
                ),
                confidence_delta=active.confidence - passive.confidence,
                tool_calls_delta=active.tool_calls - passive.tool_calls,
            )
        )

    return PassiveVerificationReport(
        benchmark_version=benchmark_version,
        scenario_ids=list(PASSIVE_VERIFICATION_SCENARIO_IDS),
        observations=observations,
        aggregates=[_aggregate(observations, mode) for mode in EVIDENCE_MODES],
        paired_deltas=paired,
    )
