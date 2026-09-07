from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agent.models import (
    AgentState,
    InvestigationPlan,
    PlanStep,
    ProposedAction,
    ProviderUsage,
)
from app.agent.providers import ReasoningProvider
from app.models.domain import Diagnosis, Hypothesis

ToolOrderMode = Literal["free", "deployment_first", "symptom_first", "adaptive"]
TOOL_ORDER_PROVIDER_MARKER = "tool-order-controlled-v1"


def _category(step: PlanStep) -> int:
    if step.tool == "inspect_deployment":
        return 0
    if step.tool == "query_metrics":
        return 1
    if step.tool == "search_logs":
        return 2
    if step.tool in {"inspect_git_diff", "search_docs", "read_file"}:
        return 3
    return 4


def _context_steps(service: str) -> list[PlanStep]:
    return [
        PlanStep(
            id="controlled-deployment-context",
            objective=f"Inspect {service} deployment context.",
            tool="inspect_deployment",
            arguments={"service": service},
            rationale=(
                "Use deployment history as observable context while keeping it distinct "
                "from causal proof."
            ),
        ),
        PlanStep(
            id="controlled-code-context",
            objective="Inspect the most recent repository diff.",
            tool="inspect_git_diff",
            arguments={"base": "HEAD~1", "head": "HEAD"},
            rationale=(
                "Inspect recent code changes as context without assuming recency implies "
                "causality."
            ),
        ),
    ]


def _same_invocation(left: PlanStep, right: PlanStep) -> bool:
    return left.tool == right.tool and left.arguments == right.arguments


def _common_step_set(plan: InvestigationPlan, service: str) -> list[PlanStep]:
    steps = [step.model_copy(deep=True) for step in plan.steps]
    for context in _context_steps(service):
        if not any(_same_invocation(context, existing) for existing in steps):
            steps.append(context)
    return steps


def _adaptive_mode(state: AgentState) -> ToolOrderMode:
    text = f"{state.incident.title} {state.incident.description}".casefold()
    if any(word in text for word in ("deploy", "release", "rollout", "change")):
        return "deployment_first"
    return "symptom_first"


def _ordered_steps(
    steps: list[PlanStep],
    *,
    mode: ToolOrderMode,
    state: AgentState,
) -> list[PlanStep]:
    effective = _adaptive_mode(state) if mode == "adaptive" else mode
    indexed = list(enumerate(steps))
    if effective == "free":
        return [step for _, step in indexed]
    if effective == "deployment_first":
        priority = {
            0: 0,
            1: 1,
            2: 2,
            3: 3,
            4: 4,
        }
    else:
        priority = {
            1: 0,
            2: 1,
            0: 2,
            3: 3,
            4: 4,
        }
    return [
        step
        for _, step in sorted(
            indexed,
            key=lambda pair: (priority[_category(pair[1])], pair[0]),
        )
    ]


@dataclass
class ControlledToolOrderProvider:
    """Vary legal investigation order while holding the tool set constant."""

    inner: ReasoningProvider
    mode: ToolOrderMode
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = f"{self.inner.name}+{TOOL_ORDER_PROVIDER_MARKER}:{self.mode}"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        plan, usage = await self.inner.plan(state)
        steps = _common_step_set(plan, state.incident.service)
        ordered = _ordered_steps(steps, mode=self.mode, state=state)
        controlled = plan.model_copy(deep=True)
        controlled.steps = ordered
        controlled.summary = (
            f"{plan.summary} Controlled tool-order treatment={self.mode}; "
            "all treatment arms receive the same legal invocation set."
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
