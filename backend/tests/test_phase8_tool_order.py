from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agent.models import (
    AgentBudget,
    AgentState,
    InvestigationPlan,
    PlanStep,
    ProposedAction,
    ProviderUsage,
)
from app.agent.tool_order import (
    TOOL_ORDER_PROVIDER_MARKER,
    ControlledToolOrderProvider,
    ToolOrderMode,
)
from app.models.domain import Diagnosis, Hypothesis, Incident, IncidentSeverity


class StubProvider:
    name = "stub-provider"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        return (
            InvestigationPlan(
                summary="Inspect observable inventory symptoms.",
                steps=[
                    PlanStep(
                        id="error-rate",
                        objective="Measure the inventory error rate.",
                        tool="query_metrics",
                        arguments={"service": state.incident.service, "metric": "error_rate"},
                        rationale="Measure the user-visible symptom first.",
                    ),
                    PlanStep(
                        id="errors",
                        objective="Inspect inventory errors.",
                        tool="search_logs",
                        arguments={
                            "service": state.incident.service,
                            "level": "ERROR",
                            "limit": 20,
                        },
                        rationale="Corroborate the metric with request-level evidence.",
                    ),
                ],
            ),
            ProviderUsage(),
        )

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        return [], ProviderUsage()

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        return False, ProviderUsage()

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        return (
            "inconclusive",
            Diagnosis(
                primary_root_cause="Insufficient evidence.",
                confidence=0.0,
                evidence_ids=[],
            ),
            ProviderUsage(),
        )

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        return None, ProviderUsage()


def _state(*, description: str = "Inventory requests are failing.") -> AgentState:
    incident = Incident(
        title="Inventory incident",
        description=description,
        severity=IncidentSeverity.P2,
        service="inventory",
        start_time=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )
    return AgentState(
        run_id=uuid4(),
        incident=incident,
        budget=AgentBudget(),
    )


def _invocations(plan: InvestigationPlan) -> set[tuple[str, str]]:
    return {
        (step.tool, json.dumps(step.arguments, sort_keys=True))
        for step in plan.steps
    }


@pytest.mark.asyncio
async def test_controlled_tool_order_holds_legal_invocation_set_constant() -> None:
    state = _state()
    plans: dict[ToolOrderMode, InvestigationPlan] = {}

    for mode in ("free", "deployment_first", "symptom_first", "adaptive"):
        provider = ControlledToolOrderProvider(StubProvider(), mode=mode)
        plan, _ = await provider.plan(state)
        plans[mode] = plan
        assert TOOL_ORDER_PROVIDER_MARKER in provider.name
        assert provider.name.endswith(f":{mode}")

    invocation_sets = [_invocations(plan) for plan in plans.values()]
    assert invocation_sets
    assert all(invocations == invocation_sets[0] for invocations in invocation_sets)
    assert len(invocation_sets[0]) == 4
    assert {tool for tool, _ in invocation_sets[0]} == {
        "query_metrics",
        "search_logs",
        "inspect_deployment",
        "inspect_git_diff",
    }


@pytest.mark.asyncio
async def test_controlled_tool_order_applies_preregistered_priorities() -> None:
    state = _state()

    deployment_plan, _ = await ControlledToolOrderProvider(
        StubProvider(), mode="deployment_first"
    ).plan(state)
    symptom_plan, _ = await ControlledToolOrderProvider(
        StubProvider(), mode="symptom_first"
    ).plan(state)
    free_plan, _ = await ControlledToolOrderProvider(
        StubProvider(), mode="free"
    ).plan(state)

    assert deployment_plan.steps[0].tool == "inspect_deployment"
    assert symptom_plan.steps[0].tool == "query_metrics"
    assert free_plan.steps[0].tool == "query_metrics"
    assert deployment_plan.steps[-1].tool == "inspect_git_diff"
    assert symptom_plan.steps[-1].tool == "inspect_git_diff"


@pytest.mark.asyncio
async def test_adaptive_order_uses_only_public_incident_text() -> None:
    release_state = _state(
        description="A visible release coincides with user-visible inventory failures."
    )
    symptom_state = _state(
        description="Inventory requests are failing with no reported recent change."
    )

    release_plan, _ = await ControlledToolOrderProvider(
        StubProvider(), mode="adaptive"
    ).plan(release_state)
    symptom_plan, _ = await ControlledToolOrderProvider(
        StubProvider(), mode="adaptive"
    ).plan(symptom_state)

    assert release_plan.steps[0].tool == "inspect_deployment"
    assert symptom_plan.steps[0].tool == "query_metrics"
