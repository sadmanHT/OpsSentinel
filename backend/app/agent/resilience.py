from __future__ import annotations

from app.agent.models import AgentState, InvestigationPlan, ProposedAction, ProviderUsage
from app.agent.providers import ReasoningProvider
from app.models.domain import Diagnosis, Hypothesis, ToolCallStatus


class DiminishingReturnsReasoningProvider:
    """Stop investigations that repeatedly fail to produce new information."""

    def __init__(self, inner: ReasoningProvider, *, max_non_progress_steps: int) -> None:
        self.inner = inner
        self.max_non_progress_steps = max_non_progress_steps
        self.name = inner.name

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        return await self.inner.plan(state)

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        return await self.inner.update_hypotheses(state)

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        enough, usage = await self.inner.enough_evidence(state)
        if enough:
            state.non_progress_count = 0
            return True, usage

        if not state.tool_history:
            return False, usage

        latest_call = state.tool_history[-1]
        failed = latest_call.status in {ToolCallStatus.FAILED, ToolCallStatus.BLOCKED}
        duplicate_evidence = (
            len(state.evidence) >= 2
            and state.evidence[-1].raw_reference is not None
            and state.evidence[-1].raw_reference == state.evidence[-2].raw_reference
        )
        if failed or duplicate_evidence:
            state.non_progress_count += 1
        else:
            state.non_progress_count = 0

        if state.non_progress_count >= self.max_non_progress_steps:
            return True, usage
        return False, usage

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        return await self.inner.diagnose(state)

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        return await self.inner.recommend(state)
