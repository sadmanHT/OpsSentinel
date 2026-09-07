from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.agent.models import (
    AgentState,
    InvestigationPlan,
    ProposedAction,
    ProviderUsage,
)
from app.agent.providers import ReasoningProvider
from app.models.domain import Diagnosis, Evidence, Hypothesis

TEMPORAL_PROVIDER_MARKER = "temporal-cause-effect-v1"
TEMPORAL_WINDOW = timedelta(minutes=30)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _payload(evidence: Evidence) -> object:
    if not evidence.raw_reference:
        return None
    try:
        record = json.loads(evidence.raw_reference)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    return record.get("payload")


def _observable_timestamps(evidence: Evidence) -> list[datetime]:
    payload = _payload(evidence)
    if not isinstance(payload, list):
        return []
    timestamps: list[datetime] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        parsed = _parse_datetime(entry.get("timestamp"))
        if parsed is not None:
            timestamps.append(parsed)
    return timestamps


def _supporting_cause_time(
    hypothesis: Hypothesis,
    evidence: list[Evidence],
    *,
    effect_time: datetime,
) -> datetime | None:
    support = set(hypothesis.supporting_evidence)
    candidates = [
        timestamp
        for item in evidence
        if item.id in support
        for timestamp in _observable_timestamps(item)
        if timestamp <= effect_time
    ]
    return min(candidates) if candidates else None


class ExplicitTemporalReasoningProvider:
    """Add observable cause/effect time constraints without benchmark hidden truth.

    The treatment uses only the public incident onset and timestamps returned by legal
    MCP log/metric queries. It never imports BenchmarkLab or reads fault-controller state.
    """

    def __init__(self, inner: ReasoningProvider) -> None:
        self.inner = inner
        self.name = f"{inner.name}+{TEMPORAL_PROVIDER_MARKER}"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        plan, usage = await self.inner.plan(state)
        effect_time = state.incident.start_time
        if effect_time.tzinfo is None or effect_time.utcoffset() is None:
            raise ValueError("explicit temporal reasoning requires a timezone-aware incident onset")
        start_time = effect_time - TEMPORAL_WINDOW
        bounded = plan.model_copy(deep=True)
        for step in bounded.steps:
            if step.tool not in {"query_metrics", "search_logs"}:
                continue
            arguments: dict[str, Any] = dict(step.arguments)
            arguments["start_time"] = start_time.isoformat()
            arguments["end_time"] = effect_time.isoformat()
            step.arguments = arguments
            step.rationale = (
                f"{step.rationale} Restrict observable evidence to the pre-onset window "
                "so causal support must not occur after the public incident onset."
            )
        bounded.summary = (
            f"{bounded.summary} Explicit temporal treatment: compare observable support "
            "against the public incident onset before accepting causal attribution."
        )
        return bounded, usage

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        hypotheses, usage = await self.inner.update_hypotheses(state)
        effect_time = state.incident.start_time
        stamped: list[Hypothesis] = []
        for hypothesis in hypotheses:
            cause_time = _supporting_cause_time(
                hypothesis,
                state.evidence,
                effect_time=effect_time,
            )
            stamped.append(
                hypothesis.model_copy(
                    update={
                        "first_possible_cause_time": cause_time,
                        "effect_time": effect_time,
                    }
                )
            )
        return stamped, usage

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        return await self.inner.enough_evidence(state)

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        return await self.inner.diagnose(state)

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        return await self.inner.recommend(state)
