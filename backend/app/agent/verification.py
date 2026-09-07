from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.models import (
    AgentState,
    InvestigationPlan,
    PlanStep,
    ProposedAction,
    ProviderUsage,
)
from app.agent.providers import ReasoningProvider
from app.models.domain import Diagnosis, Hypothesis

ACTIVE_VERIFICATION_PROVIDER_MARKER = "active-verification-v1"


def _verification_step(state: AgentState) -> PlanStep:
    service = state.incident.service
    if service == "checkout":
        return PlanStep(
            id="active-verification",
            objective="Actively verify whether checkout remains healthy under bounded load.",
            tool="rerun_load_test",
            arguments={"profile": "normal", "path": "/checkout"},
            rationale=(
                "A bounded R1 load probe provides active evidence without changing "
                "deployment state or using hidden simulator truth."
            ),
        )
    if service == "inventory":
        arguments = {
            "service": "inventory",
            "method": "GET",
            "path": "/inventory/SKU-RED",
            "expected_status": 200,
        }
    elif service == "worker":
        arguments = {
            "service": "worker",
            "method": "POST",
            "path": "/work",
            "expected_status": 200,
        }
    elif service == "payment":
        arguments = {
            "service": "payment",
            "method": "POST",
            "path": "/charge",
            "expected_status": 200,
        }
    elif service == "gateway":
        arguments = {
            "service": "gateway",
            "method": "GET",
            "path": "/checkout",
            "expected_status": 200,
        }
    else:
        arguments = {
            "service": "gateway",
            "method": "GET",
            "path": "/health",
            "expected_status": 200,
        }
    return PlanStep(
        id="active-verification",
        objective=f"Actively reproduce the observable {service} symptom.",
        tool="reproduce_request",
        arguments=arguments,
        rationale=(
            "A bounded allowlisted R1 request tests the live symptom directly while "
            "leaving remediation and benchmark ground truth out of the investigation."
        ),
    )


@dataclass
class ActiveVerificationReasoningProvider:
    """Add one bounded active verification probe to an otherwise unchanged plan."""

    inner: ReasoningProvider
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = f"{self.inner.name}+{ACTIVE_VERIFICATION_PROVIDER_MARKER}"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        plan, usage = await self.inner.plan(state)
        controlled = plan.model_copy(deep=True)
        verification = _verification_step(state)
        insertion = 1 if controlled.steps else 0
        controlled.steps.insert(insertion, verification)
        controlled.summary = (
            f"{plan.summary} Active verification evidence is enabled through one "
            "bounded R1 probe; passive investigation steps remain unchanged."
        )
        return controlled, usage

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        return await self.inner.update_hypotheses(state)

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
