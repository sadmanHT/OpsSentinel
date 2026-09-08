from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.agent.compound import (
    COMPOUND_EVIDENCE_PROVIDER_MARKER,
    UNRESOLVED_EVIDENCE_PROVIDER_MARKER,
    CompoundEvidencePlanProvider,
    UnresolvedEvidenceStoppingProvider,
)
from app.agent.models import AgentState, InvestigationPlan, PlanStep, ProviderUsage
from app.agent.providers import ReasoningProvider


class AlwaysEnoughProvider:
    name = "test-provider"

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        return True, ProviderUsage()


def _state(plan: InvestigationPlan | None = None) -> AgentState:
    return cast(AgentState, SimpleNamespace(plan=plan))


@pytest.mark.asyncio
async def test_compound_plan_is_fixed_cross_service_passive_surface() -> None:
    inner = cast(ReasoningProvider, AlwaysEnoughProvider())
    provider = CompoundEvidencePlanProvider(inner)

    plan, usage = await provider.plan(_state())

    assert usage.total_tokens == 0
    assert provider.name.endswith(COMPOUND_EVIDENCE_PROVIDER_MARKER)
    assert [step.id for step in plan.steps] == [
        "checkout-db-query-count",
        "checkout-request-logs",
        "inventory-db-connections",
        "inventory-errors",
        "worker-disk",
        "worker-memory",
        "worker-restarts",
        "worker-errors",
        "payment-warnings",
        "gateway-errors",
    ]
    assert [step.tool for step in plan.steps] == [
        "query_metrics",
        "search_logs",
        "query_metrics",
        "search_logs",
        "query_metrics",
        "query_metrics",
        "query_metrics",
        "search_logs",
        "search_logs",
        "search_logs",
    ]
    assert all(step.required for step in plan.steps)
    assert all(not step.completed for step in plan.steps)


@pytest.mark.asyncio
async def test_unresolved_stopping_requires_all_required_steps_complete() -> None:
    inner = cast(ReasoningProvider, AlwaysEnoughProvider())
    provider = UnresolvedEvidenceStoppingProvider(inner)
    plan = InvestigationPlan(
        summary="test",
        steps=[
            PlanStep(
                id="a",
                objective="a",
                tool="query_metrics",
                arguments={"service": "worker", "metric": "disk_usage"},
                rationale="a",
            ),
            PlanStep(
                id="b",
                objective="b",
                tool="search_logs",
                arguments={"service": "worker", "level": "ERROR"},
                rationale="b",
            ),
        ],
    )

    enough, _ = await provider.enough_evidence(_state(plan))
    assert enough is False

    plan.steps[0].completed = True
    enough, _ = await provider.enough_evidence(_state(plan))
    assert enough is False

    plan.steps[1].completed = True
    enough, _ = await provider.enough_evidence(_state(plan))
    assert enough is True
    assert provider.name.endswith(UNRESOLVED_EVIDENCE_PROVIDER_MARKER)
