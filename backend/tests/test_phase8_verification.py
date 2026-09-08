from __future__ import annotations

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
from app.agent.verification import (
    ACTIVE_VERIFICATION_PROVIDER_MARKER,
    ActiveVerificationReasoningProvider,
)
from app.models.domain import Diagnosis, Hypothesis, Incident, IncidentSeverity


class StubProvider:
    name = "stub-provider"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        return (
            InvestigationPlan(
                summary="Inspect passive evidence.",
                steps=[
                    PlanStep(
                        id="metrics",
                        objective="Measure the symptom.",
                        tool="query_metrics",
                        arguments={
                            "service": state.incident.service,
                            "metric": "error_rate",
                        },
                        rationale="Start with the observed symptom.",
                    ),
                    PlanStep(
                        id="logs",
                        objective="Inspect recent errors.",
                        tool="search_logs",
                        arguments={
                            "service": state.incident.service,
                            "level": "ERROR",
                            "limit": 20,
                        },
                        rationale="Corroborate metrics with passive log evidence.",
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


def _state(service: str) -> AgentState:
    return AgentState(
        run_id=uuid4(),
        incident=Incident(
            title=f"{service} incident",
            description=f"User-visible {service} symptoms are present.",
            severity=IncidentSeverity.P2,
            service=service,
            start_time=datetime(2026, 9, 8, 5, 0, tzinfo=UTC),
        ),
        budget=AgentBudget(),
    )


@pytest.mark.asyncio
async def test_active_verification_adds_exactly_one_probe_after_first_passive_step() -> None:
    state = _state("inventory")
    baseline, _ = await StubProvider().plan(state)
    provider = ActiveVerificationReasoningProvider(StubProvider())

    controlled, _ = await provider.plan(state)

    assert ACTIVE_VERIFICATION_PROVIDER_MARKER in provider.name
    assert len(controlled.steps) == len(baseline.steps) + 1
    assert controlled.steps[0] == baseline.steps[0]
    assert controlled.steps[2:] == baseline.steps[1:]
    probe = controlled.steps[1]
    assert probe.tool == "reproduce_request"
    assert probe.arguments == {
        "service": "inventory",
        "method": "GET",
        "path": "/inventory/SKU-RED",
        "expected_status": 200,
    }
    assert sum(step.id == "active-verification" for step in controlled.steps) == 1


@pytest.mark.asyncio
async def test_checkout_uses_bounded_load_verification_probe() -> None:
    controlled, _ = await ActiveVerificationReasoningProvider(StubProvider()).plan(
        _state("checkout")
    )

    probe = controlled.steps[1]
    assert probe.tool == "rerun_load_test"
    assert probe.arguments == {"profile": "normal", "path": "/checkout"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "method", "path"),
    [
        ("payment", "POST", "/charge"),
        ("worker", "POST", "/work"),
        ("gateway", "GET", "/checkout"),
    ],
)
async def test_service_specific_request_probe_is_allowlisted(
    service: str,
    method: str,
    path: str,
) -> None:
    controlled, _ = await ActiveVerificationReasoningProvider(StubProvider()).plan(
        _state(service)
    )

    probe = controlled.steps[1]
    assert probe.tool == "reproduce_request"
    assert probe.arguments["service"] == service
    assert probe.arguments["method"] == method
    assert probe.arguments["path"] == path
    assert probe.arguments["expected_status"] == 200
