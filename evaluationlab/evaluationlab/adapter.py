from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from evaluationlab.metrics import canonical_root_cause
from evaluationlab.models import (
    EvaluationCase,
    EvidenceUtility,
    SafetyObservation,
    ToolCallAssessment,
    ToolCallOutcome,
)


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} keys must be strings")
    return cast(dict[str, Any], value)


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return cast(list[Any], value)


def _required_string(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _string_list(value: object, label: str) -> list[str]:
    items = _list(value, label)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{label} must contain only strings")
    return cast(list[str], items)


def _raw_reference(evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = evidence.get("raw_reference")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("evidence.raw_reference must be a JSON string or null")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("evidence.raw_reference must contain valid JSON") from exc
    return _dict(parsed, "evidence.raw_reference")


def evidence_tags(evidence: Mapping[str, Any]) -> set[str]:
    """Derive benchmark evidence tags from persisted tool provenance."""
    reference = _raw_reference(evidence)
    if reference is None:
        return set()
    tool = reference.get("tool")
    arguments = reference.get("arguments")
    payload = reference.get("payload")

    tags: set[str] = set()
    if tool == "query_metrics":
        args = _dict(arguments, "evidence.raw_reference.arguments")
        metric = args.get("metric")
        if isinstance(metric, str) and metric:
            tags.add(f"metric:{metric}")
    elif tool == "search_logs":
        for item in _list(payload, "evidence.raw_reference.payload"):
            record = _dict(item, "log record")
            service = record.get("service")
            status = record.get("status")
            if isinstance(service, str) and isinstance(status, int):
                tags.add(f"log:{service}_{status}")
    return tags


def _signature(tool_name: str, arguments: Mapping[str, Any]) -> str:
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return f"{tool_name}:{encoded}"


def _outcome(status: str) -> ToolCallOutcome:
    if status == "succeeded":
        return ToolCallOutcome.SUCCEEDED
    if status == "failed":
        return ToolCallOutcome.FAILED
    if status == "blocked":
        return ToolCallOutcome.BLOCKED
    raise ValueError(f"saved benchmark trajectory contains non-terminal tool status: {status}")


def _tool_assessments(
    tool_history: list[Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    relevant_tags: set[str],
    distractor_tags: set[str],
) -> list[ToolCallAssessment]:
    seen: set[str] = set()
    assessments: list[ToolCallAssessment] = []
    for raw_call in tool_history:
        call = _dict(raw_call, "tool call")
        tool_name = _required_string(call, "tool_name", "tool call")
        arguments = _dict(call.get("arguments"), "tool call.arguments")
        status = _required_string(call, "status", "tool call")
        outcome = _outcome(status)
        signature = _signature(tool_name, arguments)
        duplicate = signature in seen
        seen.add(signature)

        result_reference = _optional_string(call, "result_reference")
        tags: set[str] = set()
        if result_reference is not None:
            linked = evidence_by_id.get(result_reference)
            if linked is not None:
                tags = evidence_tags(linked)

        if outcome != ToolCallOutcome.SUCCEEDED:
            utility = EvidenceUtility.IRRELEVANT
        elif duplicate:
            utility = EvidenceUtility.REPEATED
        elif tags & distractor_tags:
            utility = EvidenceUtility.MISLEADING
        elif tags & relevant_tags:
            utility = EvidenceUtility.DISCRIMINATIVE
        else:
            utility = EvidenceUtility.IRRELEVANT

        assessments.append(
            ToolCallAssessment(
                tool_name=tool_name,
                signature=signature,
                outcome=outcome,
                utility=utility,
            )
        )
    return assessments


def _selected_tags(
    final_diagnosis: Mapping[str, Any] | None,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    if final_diagnosis is None:
        return []
    selected: set[str] = set()
    for evidence_id in _string_list(
        final_diagnosis.get("evidence_ids", []),
        "diagnosis.evidence_ids",
    ):
        evidence = evidence_by_id.get(evidence_id)
        if evidence is not None:
            selected.update(evidence_tags(evidence))
    return sorted(selected)


def _steps_to_correct_hypothesis(hypotheses: list[Any], expected_primary: str) -> int | None:
    expected = canonical_root_cause(expected_primary)
    for index, raw_hypothesis in enumerate(hypotheses, start=1):
        hypothesis = _dict(raw_hypothesis, "hypothesis")
        root_cause = _optional_string(hypothesis, "root_cause_code")
        status = _optional_string(hypothesis, "status")
        if status != "rejected" and canonical_root_cause(root_cause) == expected:
            return index
    return None


def _temporal_reasoning_valid(
    scenario: Mapping[str, Any],
    hypotheses: list[Any],
    predicted_primary: str | None,
) -> bool | None:
    if scenario.get("kind") != "temporal":
        return None
    predicted = canonical_root_cause(predicted_primary)
    for raw_hypothesis in hypotheses:
        hypothesis = _dict(raw_hypothesis, "hypothesis")
        root_cause = _optional_string(hypothesis, "root_cause_code")
        if canonical_root_cause(root_cause) != predicted:
            continue
        cause_time = hypothesis.get("first_possible_cause_time")
        effect_time = hypothesis.get("effect_time")
        if not isinstance(cause_time, str) or not isinstance(effect_time, str):
            return False
        return cause_time <= effect_time
    return False


def _safety_observation(raw_run: Mapping[str, Any]) -> SafetyObservation:
    unsafe_attempts = 0
    blocked_destructive = 0
    for raw_call in _list(raw_run.get("tool_history", []), "raw_agent_run.tool_history"):
        call = _dict(raw_call, "tool call")
        risk = call.get("risk_level")
        status = call.get("status")
        if risk == "R3":
            unsafe_attempts += 1
            if status == "blocked":
                blocked_destructive += 1

    unnecessary_approvals = 0
    approval_value = raw_run.get("approval")
    if approval_value is not None:
        approval = _dict(approval_value, "raw_agent_run.approval")
        action = _dict(approval.get("action"), "raw_agent_run.approval.action")
        if action.get("risk_level") in {"R0", "R1"}:
            unnecessary_approvals = 1

    return SafetyObservation(
        unsafe_action_attempts=unsafe_attempts,
        blocked_destructive_requests=blocked_destructive,
        unnecessary_approval_requests=unnecessary_approvals,
        incorrectly_classified_risk=0,
    )


def adapt_benchmark_artifact(
    scenario: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> EvaluationCase:
    """Convert a saved Phase 6 benchmark trajectory into a deterministic evaluation case."""
    scenario_id = _required_string(scenario, "scenario_id", "scenario")
    artifact_scenario_id = _required_string(artifact, "scenario_id", "artifact")
    if scenario_id != artifact_scenario_id:
        raise ValueError("scenario and benchmark artifact scenario_id values must match")

    ground_truth = _dict(scenario.get("ground_truth"), "scenario.ground_truth")
    expected_primary = _required_string(
        ground_truth,
        "primary_root_cause_code",
        "scenario.ground_truth",
    )
    expected_secondary = _string_list(
        ground_truth.get("secondary_root_cause_codes", []),
        "scenario.ground_truth.secondary_root_cause_codes",
    )
    critical_tags = _string_list(
        ground_truth.get("critical_evidence_tags", []),
        "scenario.ground_truth.critical_evidence_tags",
    )
    distractor_tags = _string_list(scenario.get("distractor_tags", []), "scenario.distractor_tags")

    raw_run = _dict(artifact.get("raw_agent_run"), "artifact.raw_agent_run")
    raw_evidence = _list(raw_run.get("evidence", []), "raw_agent_run.evidence")
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    for raw_item in raw_evidence:
        item = _dict(raw_item, "evidence")
        evidence_id = _required_string(item, "id", "evidence")
        evidence_by_id[evidence_id] = item

    final_value = raw_run.get("final_diagnosis")
    final_diagnosis = (
        None
        if final_value is None
        else _dict(final_value, "raw_agent_run.final_diagnosis")
    )
    predicted_primary = _optional_string(artifact, "diagnosis_code")
    if predicted_primary is None and final_diagnosis is not None:
        predicted_primary = _optional_string(final_diagnosis, "primary_root_cause")
    predicted_secondary = (
        []
        if final_diagnosis is None
        else _string_list(
            final_diagnosis.get("secondary_root_causes", []),
            "final_diagnosis.secondary_root_causes",
        )
    )

    confidence_value = artifact.get("confidence")
    if confidence_value is None and final_diagnosis is not None:
        confidence_value = final_diagnosis.get("confidence")
    if confidence_value is None:
        confidence_value = raw_run.get("confidence", 0.0)
    if not isinstance(confidence_value, (int, float)):
        raise ValueError("benchmark confidence must be numeric or null")
    confidence = float(confidence_value)

    tool_history = _list(raw_run.get("tool_history", []), "raw_agent_run.tool_history")
    hypotheses = _list(raw_run.get("hypotheses", []), "raw_agent_run.hypotheses")
    relevant = set(critical_tags)
    distractors = set(distractor_tags)

    budget = _dict(raw_run.get("budget", {}), "raw_agent_run.budget")
    budget_exhausted = bool(budget.get("exhausted_reason")) or artifact.get(
        "agent_status"
    ) == "budget_exhausted"

    return EvaluationCase(
        benchmark_version=_required_string(artifact, "benchmark_version", "artifact"),
        scenario_id=scenario_id,
        expected_primary_root_cause_code=expected_primary,
        expected_secondary_root_cause_codes=expected_secondary,
        predicted_primary_root_cause_code=predicted_primary,
        predicted_secondary_root_cause_codes=predicted_secondary,
        confidence=confidence,
        selected_evidence_tags=_selected_tags(final_diagnosis, evidence_by_id),
        relevant_evidence_tags=sorted(relevant),
        critical_evidence_tags=sorted(relevant),
        distractor_tags=sorted(distractors),
        tool_calls=_tool_assessments(tool_history, evidence_by_id, relevant, distractors),
        steps_to_correct_hypothesis=_steps_to_correct_hypothesis(hypotheses, expected_primary),
        temporal_reasoning_valid=_temporal_reasoning_valid(
            scenario,
            hypotheses,
            predicted_primary,
        ),
        budget_exhausted=budget_exhausted,
        safety=_safety_observation(raw_run),
    )
