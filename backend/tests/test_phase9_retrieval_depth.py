from __future__ import annotations

from typing import cast

import pytest

from app.agent.models import AgentState, InvestigationPlan, PlanStep, ProviderUsage
from app.agent.providers import ReasoningProvider
from app.agent.retrieval import (
    RETRIEVAL_DEPTH_PROVIDER_MARKER,
    CappedRetrievalDepthProvider,
)


class FakePlanProvider:
    name = "fake-provider"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        del state
        return (
            InvestigationPlan(
                summary="baseline",
                steps=[
                    PlanStep(
                        id="wide-logs",
                        objective="Read a broad log sample.",
                        tool="search_logs",
                        arguments={"service": "checkout", "limit": 20},
                        rationale="Broad log context.",
                    ),
                    PlanStep(
                        id="narrow-logs",
                        objective="Read an already bounded log sample.",
                        tool="search_logs",
                        arguments={"service": "inventory", "limit": 3},
                        rationale="Small log context.",
                    ),
                    PlanStep(
                        id="not-retrieval",
                        objective="Exercise a non-log tool argument.",
                        tool="query_metrics",
                        arguments={"service": "checkout", "metric": "error_rate", "limit": 50},
                        rationale="Non-log tools must be untouched.",
                    ),
                ],
            ),
            ProviderUsage(),
        )


@pytest.mark.asyncio
async def test_retrieval_depth_only_reduces_existing_log_limits() -> None:
    provider = CappedRetrievalDepthProvider(
        cast(ReasoningProvider, FakePlanProvider()),
        max_records=5,
    )

    plan, usage = await provider.plan(cast(AgentState, object()))

    assert usage == ProviderUsage()
    assert [step.arguments["limit"] for step in plan.steps] == [5, 3, 50]
    assert "capped at 5 records" in plan.summary


@pytest.mark.asyncio
async def test_retrieval_depth_never_increases_existing_limit() -> None:
    provider = CappedRetrievalDepthProvider(
        cast(ReasoningProvider, FakePlanProvider()),
        max_records=100,
    )

    plan, _ = await provider.plan(cast(AgentState, object()))

    assert [step.arguments["limit"] for step in plan.steps] == [20, 3, 50]
    assert plan.summary == "baseline"


def test_retrieval_depth_provider_identity_and_validation() -> None:
    provider = CappedRetrievalDepthProvider(
        cast(ReasoningProvider, FakePlanProvider()),
        max_records=7,
    )

    assert RETRIEVAL_DEPTH_PROVIDER_MARKER in provider.name
    assert provider.name.endswith("-7")
    with pytest.raises(ValueError, match="max_records must be at least 1"):
        CappedRetrievalDepthProvider(
            cast(ReasoningProvider, FakePlanProvider()),
            max_records=0,
        )
