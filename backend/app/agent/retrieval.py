from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.models import (
    AgentState,
    InvestigationPlan,
    ProposedAction,
    ProviderUsage,
)
from app.agent.providers import ReasoningProvider
from app.models.domain import Diagnosis, Hypothesis

RETRIEVAL_DEPTH_PROVIDER_MARKER = "retrieval-depth-cap-v1"


@dataclass
class CappedRetrievalDepthProvider:
    """Bound records returned by existing legal log-retrieval plan steps.

    This wrapper never adds a new tool call and never increases an existing retrieval
    limit. It only reduces explicit ``search_logs`` limits so retrieval depth can be
    varied independently from the investigation tool-call budget.
    """

    inner: ReasoningProvider
    max_records: int
    name: str = field(init=False)

    def __post_init__(self) -> None:
        if self.max_records < 1:
            raise ValueError("max_records must be at least 1")
        self.name = (
            f"{self.inner.name}+{RETRIEVAL_DEPTH_PROVIDER_MARKER}-{self.max_records}"
        )

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        plan, usage = await self.inner.plan(state)
        controlled = plan.model_copy(deep=True)
        changed = False
        for step in controlled.steps:
            if step.tool != "search_logs":
                continue
            limit = step.arguments.get("limit")
            if (
                isinstance(limit, int)
                and not isinstance(limit, bool)
                and limit > self.max_records
            ):
                arguments = dict(step.arguments)
                arguments["limit"] = self.max_records
                step.arguments = arguments
                changed = True
        if changed:
            controlled.summary = (
                f"{plan.summary} Log retrieval is capped at {self.max_records} records "
                "per existing search step for the Phase 9 retrieval-depth treatment."
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
