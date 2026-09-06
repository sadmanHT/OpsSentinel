from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from app.agent.models import (
    AgentNode,
    AgentState,
    InvestigationPlan,
    ProposedAction,
    ProviderUsage,
)
from app.agent.phase5_runtime import Phase5Runtime
from app.agent.providers import ReasoningProvider, ReasoningProviderError
from app.agent.runtime import AgentRuntime, GraphPayload
from app.agent.store import AgentStore
from app.mcp.registry import ToolRegistry
from app.models.domain import Diagnosis, Hypothesis


def _step_signature(tool: str, arguments: dict[str, object]) -> str:
    return json.dumps({"tool": tool, "arguments": arguments}, default=str, sort_keys=True)


def _observed_signatures(state: AgentState) -> set[str]:
    return {
        _step_signature(call.tool_name, call.arguments)
        for call in state.tool_history
    }


def _combine_usage(left: ProviderUsage, right: ProviderUsage) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        estimated_cost=left.estimated_cost + right.estimated_cost,
    )


class ReactiveReasoningProvider:
    """Re-plan one legal investigation action at a time after every observation.

    The wrapped provider still determines legal investigation steps and evidence-grounded
    diagnosis. This adapter changes only control flow: it selects one unseen action from a
    freshly generated plan, observes the result, updates hypotheses, and then re-plans.
    """

    def __init__(self, inner: ReasoningProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.plan_calls = 0
        self._full_plans: dict[UUID, InvestigationPlan] = {}

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        full_plan, usage = await self.inner.plan(state)
        self.plan_calls += 1
        self._full_plans[state.run_id] = full_plan.model_copy(deep=True)
        observed = _observed_signatures(state)
        selected = next(
            (
                step
                for step in full_plan.steps
                if _step_signature(step.tool, step.arguments) not in observed
            ),
            None,
        )
        if selected is None:
            selected = full_plan.steps[-1].model_copy(update={"completed": True})
        else:
            selected = selected.model_copy(update={"completed": False})
        return (
            InvestigationPlan(
                summary=(
                    "Reactive ReAct control: execute one legal action, observe evidence, "
                    f"then re-plan. Base plan: {full_plan.summary}"
                ),
                steps=[selected],
            ),
            usage,
        )

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        return await self.inner.update_hypotheses(state)

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        planning_usage = ProviderUsage()
        full_plan = self._full_plans.get(state.run_id)
        if full_plan is None:
            full_plan, planning_usage = await self.inner.plan(state)
            self._full_plans[state.run_id] = full_plan.model_copy(deep=True)

        observed = _observed_signatures(state)
        completed_plan = full_plan.model_copy(deep=True)
        for step in completed_plan.steps:
            step.completed = _step_signature(step.tool, step.arguments) in observed

        current_plan = state.plan
        state.plan = completed_plan
        try:
            enough, usage = await self.inner.enough_evidence(state)
        finally:
            state.plan = current_plan
        return enough, _combine_usage(planning_usage, usage)

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        return await self.inner.diagnose(state)

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        return await self.inner.recommend(state)


class ReactiveAgentRuntime(AgentRuntime):
    """AgentRuntime variant that refreshes its one-step plan after each observation."""

    architecture_version = "phase4-reactive-react-v1"

    async def _select_tool(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        if state.plan is not None and all(step.completed for step in state.plan.steps):
            try:
                plan, usage = await self.provider.plan(state)
            except ReasoningProviderError as exc:
                self._provider_failure(state, exc)
                return self._checkpoint(state, AgentNode.REPORT)
            state.plan = plan
            if not self._apply_usage(state, usage):
                return self._checkpoint(state, AgentNode.REPORT)
        return await super()._select_tool({"state": state})

    async def _enough_evidence(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        try:
            enough, usage = await self.provider.enough_evidence(state)
        except ReasoningProviderError as exc:
            self._provider_failure(state, exc)
            return self._checkpoint(state, AgentNode.REPORT)
        if not self._apply_usage(state, usage):
            return self._checkpoint(state, AgentNode.REPORT)
        if enough:
            return self._checkpoint(state, AgentNode.DIAGNOSE)
        reason = self._budget_reason(state)
        if reason is not None:
            self._mark_exhausted(state, reason)
            return self._checkpoint(state, AgentNode.REPORT)
        return self._checkpoint(state, AgentNode.SELECT_TOOL)


class ReactivePhase5Runtime(Phase5Runtime):
    """Phase 5 safety wrapper using the reactive investigator below it."""

    architecture_version = "phase5-safe-operational-agent-v1-reactive-react-v1"

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        provider: ReasoningProvider,
        store: AgentStore,
        interrupt_after: Sequence[AgentNode] | None = None,
    ) -> None:
        super().__init__(
            registry=registry,
            provider=provider,
            store=store,
            interrupt_after=interrupt_after,
        )
        self.investigation = ReactiveAgentRuntime(
            registry=registry,
            provider=ReactiveReasoningProvider(provider),
            store=store,
            interrupt_after=interrupt_after,
        )
