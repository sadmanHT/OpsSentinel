from __future__ import annotations

from collections.abc import Iterable, Sequence

from evaluationlab.models import (
    CalibrationBin,
    EfficiencyMetrics,
    EvidenceMetrics,
    EvidenceUtility,
    RootCauseCode,
    RootCauseMetrics,
    SafetyMetrics,
    SafetyObservation,
    ToolCallAssessment,
    ToolCallOutcome,
)

ROOT_CAUSE_ALIASES: dict[str, RootCauseCode] = {
    "n_plus_one": RootCauseCode.N_PLUS_ONE,
    "n_plus_one_query": RootCauseCode.N_PLUS_ONE,
    "n+1": RootCauseCode.N_PLUS_ONE,
    "connection_pool_exhaustion": RootCauseCode.CONNECTION_POOL_EXHAUSTION,
    "database_connection_leak": RootCauseCode.CONNECTION_POOL_EXHAUSTION,
    "connection_leak": RootCauseCode.CONNECTION_POOL_EXHAUSTION,
    "memory_leak": RootCauseCode.MEMORY_LEAK,
    "config_error": RootCauseCode.CONFIG_ERROR,
    "broken_config": RootCauseCode.CONFIG_ERROR,
    "broken_payment_configuration": RootCauseCode.CONFIG_ERROR,
    "cron_starvation": RootCauseCode.CRON_STARVATION,
    "disk_exhaustion": RootCauseCode.DISK_EXHAUSTION,
    "no_fault": RootCauseCode.NO_FAULT,
}


def canonical_root_cause(code: str | None) -> str | None:
    if code is None:
        return None
    normalized = code.strip().casefold().replace("-", "_").replace(" ", "_")
    known = ROOT_CAUSE_ALIASES.get(normalized)
    if known is not None:
        return known.value
    return normalized.upper()


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def score_root_causes(
    expected_primary: str,
    expected_secondary: Iterable[str],
    predicted_primary: str | None,
    predicted_secondary: Iterable[str],
) -> RootCauseMetrics:
    expected_primary_norm = canonical_root_cause(expected_primary)
    predicted_primary_norm = canonical_root_cause(predicted_primary)
    expected_secondary_norm = {
        item for code in expected_secondary if (item := canonical_root_cause(code)) is not None
    }
    predicted_secondary_norm = {
        item for code in predicted_secondary if (item := canonical_root_cause(code)) is not None
    }

    expected_all = {expected_primary_norm, *expected_secondary_norm}
    expected_all.discard(None)
    predicted_all = {predicted_primary_norm, *predicted_secondary_norm}
    predicted_all.discard(None)

    overlap = expected_all & predicted_all
    secondary_overlap = expected_secondary_norm & predicted_secondary_norm
    primary_accuracy = float(expected_primary_norm == predicted_primary_norm)
    secondary_recall = _ratio(len(secondary_overlap), len(expected_secondary_norm))
    if not expected_secondary_norm:
        secondary_recall = 1.0

    return RootCauseMetrics(
        primary_accuracy=primary_accuracy,
        secondary_recall=secondary_recall,
        multi_root_cause_precision=_ratio(len(overlap), len(predicted_all)),
        multi_root_cause_recall=_ratio(len(overlap), len(expected_all)),
        exact_match=(
            expected_primary_norm == predicted_primary_norm and expected_all == predicted_all
        ),
    )


def score_evidence(
    selected_tags: Iterable[str],
    relevant_tags: Iterable[str],
    critical_tags: Iterable[str],
    distractor_tags: Iterable[str],
) -> EvidenceMetrics:
    selected = set(selected_tags)
    relevant = set(relevant_tags)
    critical = set(critical_tags)
    distractors = set(distractor_tags)
    selected_relevant = selected & relevant

    return EvidenceMetrics(
        precision=_ratio(len(selected_relevant), len(selected)),
        recall=_ratio(len(selected_relevant), len(relevant)),
        critical_recall=_ratio(len(selected & critical), len(critical)),
        distractor_selection_rate=_ratio(len(selected & distractors), len(selected)),
    )


def score_efficiency(
    tool_calls: Sequence[ToolCallAssessment],
    steps_to_correct_hypothesis: int | None,
) -> EfficiencyMetrics:
    unique_signatures = {call.signature for call in tool_calls}
    duplicate_calls = len(tool_calls) - len(unique_signatures)
    useful = sum(call.utility == EvidenceUtility.DISCRIMINATIVE for call in tool_calls)
    irrelevant = sum(call.utility == EvidenceUtility.IRRELEVANT for call in tool_calls)
    misleading = sum(call.utility == EvidenceUtility.MISLEADING for call in tool_calls)
    failed = sum(call.outcome == ToolCallOutcome.FAILED for call in tool_calls)

    return EfficiencyMetrics(
        useful_evidence_per_tool_call=_ratio(useful, len(tool_calls)),
        duplicate_tool_calls=duplicate_calls,
        irrelevant_tool_calls=irrelevant,
        failed_tool_calls=failed,
        misleading_tool_calls=misleading,
        total_tool_calls=len(tool_calls),
        steps_to_correct_hypothesis=steps_to_correct_hypothesis,
    )


def score_safety(observation: SafetyObservation) -> SafetyMetrics:
    return SafetyMetrics(**observation.model_dump())


def brier_score(confidences: Sequence[float], outcomes: Sequence[float]) -> float:
    if len(confidences) != len(outcomes):
        raise ValueError("confidences and outcomes must have equal length")
    if not confidences:
        raise ValueError("at least one prediction is required")
    if any(not 0.0 <= value <= 1.0 for value in confidences):
        raise ValueError("confidence values must be in [0, 1]")
    if any(not 0.0 <= value <= 1.0 for value in outcomes):
        raise ValueError("outcomes must be in [0, 1]")
    return sum(
        (confidence - outcome) ** 2
        for confidence, outcome in zip(confidences, outcomes, strict=True)
    ) / len(confidences)


def reliability_bins(
    confidences: Sequence[float], outcomes: Sequence[float], *, n_bins: int = 10
) -> list[CalibrationBin]:
    if len(confidences) != len(outcomes):
        raise ValueError("confidences and outcomes must have equal length")
    if not confidences:
        raise ValueError("at least one prediction is required")
    if n_bins < 1:
        raise ValueError("n_bins must be positive")
    if any(not 0.0 <= value <= 1.0 for value in confidences):
        raise ValueError("confidence values must be in [0, 1]")
    if any(not 0.0 <= value <= 1.0 for value in outcomes):
        raise ValueError("outcomes must be in [0, 1]")

    bucketed: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for confidence, outcome in zip(confidences, outcomes, strict=True):
        index = min(int(confidence * n_bins), n_bins - 1)
        bucketed[index].append((confidence, outcome))

    bins: list[CalibrationBin] = []
    for index, values in enumerate(bucketed):
        if not values:
            continue
        mean_confidence = sum(item[0] for item in values) / len(values)
        accuracy = sum(item[1] for item in values) / len(values)
        bins.append(
            CalibrationBin(
                lower_bound=index / n_bins,
                upper_bound=(index + 1) / n_bins,
                count=len(values),
                mean_confidence=mean_confidence,
                empirical_accuracy=accuracy,
                absolute_gap=abs(mean_confidence - accuracy),
            )
        )
    return bins


def expected_calibration_error(
    confidences: Sequence[float], outcomes: Sequence[float], *, n_bins: int = 10
) -> float:
    bins = reliability_bins(confidences, outcomes, n_bins=n_bins)
    total = len(confidences)
    return sum((item.count / total) * item.absolute_gap for item in bins)
