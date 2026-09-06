from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.agent.models import (
    AgentBudget,
    AgentNode,
    AgentReport,
    AgentState,
    GroundedClaim,
    ProviderUsage,
    VerificationResult,
)
from app.agent.providers import ReasoningProvider, ReasoningProviderError
from app.agent.store import AgentStore
from app.mcp.models import ToolInvocation
from app.mcp.registry import ToolRegistry
from app.models.domain import (
    AgentRunStatus,
    Diagnosis,
    Evidence,
    Hypothesis,
    Incident,
    ToolCall,
    VerificationStatus,
    utc_now,
)


class GraphPayload(TypedDict):
    state: AgentState


class AgentRuntime:
    architecture_version = "phase4-single-agent-v1"

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        provider: ReasoningProvider,
        store: AgentStore,
        interrupt_after: Sequence[AgentNode] | None = None,
    ) -> None:
        self.registry = registry
        self.provider = provider
        self.store = store
        self.interrupt_after = tuple(interrupt_after or ())
        self.graph: Any = self._build_graph(interrupt_after)

    def _build_graph(self, interrupt_after: Sequence[AgentNode] | None) -> Any:
        builder = StateGraph(GraphPayload)
        builder.add_node(AgentNode.TRIAGE.value, self._triage)
        builder.add_node(AgentNode.PLAN.value, self._plan)
        builder.add_node(AgentNode.SELECT_TOOL.value, self._select_tool)
        builder.add_node(AgentNode.EXECUTE_TOOL.value, self._execute_tool)
        builder.add_node(AgentNode.STORE_EVIDENCE.value, self._store_evidence)
        builder.add_node(AgentNode.UPDATE_HYPOTHESIS.value, self._update_hypothesis)
        builder.add_node(AgentNode.ENOUGH_EVIDENCE.value, self._enough_evidence)
        builder.add_node(AgentNode.DIAGNOSE.value, self._diagnose)
        builder.add_node(AgentNode.RECOMMEND.value, self._recommend)
        builder.add_node(AgentNode.REPORT.value, self._report)

        entry_mapping: dict[str, Any] = {
            node.value: node.value for node in AgentNode if node not in {AgentNode.END}
        }
        entry_mapping[AgentNode.END.value] = END
        builder.add_conditional_edges(START, self._entry_router, entry_mapping)

        builder.add_edge(AgentNode.TRIAGE.value, AgentNode.PLAN.value)
        builder.add_conditional_edges(
            AgentNode.PLAN.value,
            self._next_router,
            {
                AgentNode.SELECT_TOOL.value: AgentNode.SELECT_TOOL.value,
                AgentNode.REPORT.value: AgentNode.REPORT.value,
            },
        )
        builder.add_conditional_edges(
            AgentNode.SELECT_TOOL.value,
            self._next_router,
            {
                AgentNode.EXECUTE_TOOL.value: AgentNode.EXECUTE_TOOL.value,
                AgentNode.DIAGNOSE.value: AgentNode.DIAGNOSE.value,
                AgentNode.REPORT.value: AgentNode.REPORT.value,
            },
        )
        builder.add_edge(AgentNode.EXECUTE_TOOL.value, AgentNode.STORE_EVIDENCE.value)
        builder.add_edge(AgentNode.STORE_EVIDENCE.value, AgentNode.UPDATE_HYPOTHESIS.value)
        builder.add_conditional_edges(
            AgentNode.UPDATE_HYPOTHESIS.value,
            self._next_router,
            {
                AgentNode.ENOUGH_EVIDENCE.value: AgentNode.ENOUGH_EVIDENCE.value,
                AgentNode.REPORT.value: AgentNode.REPORT.value,
            },
        )
        builder.add_conditional_edges(
            AgentNode.ENOUGH_EVIDENCE.value,
            self._next_router,
            {
                AgentNode.SELECT_TOOL.value: AgentNode.SELECT_TOOL.value,
                AgentNode.DIAGNOSE.value: AgentNode.DIAGNOSE.value,
                AgentNode.REPORT.value: AgentNode.REPORT.value,
            },
        )
        builder.add_conditional_edges(
            AgentNode.DIAGNOSE.value,
            self._next_router,
            {
                AgentNode.RECOMMEND.value: AgentNode.RECOMMEND.value,
                AgentNode.REPORT.value: AgentNode.REPORT.value,
            },
        )
        builder.add_edge(AgentNode.RECOMMEND.value, AgentNode.REPORT.value)
        builder.add_edge(AgentNode.REPORT.value, END)

        interrupt_names = [node.value for node in interrupt_after] if interrupt_after else None
        return builder.compile(interrupt_after=interrupt_names)

    async def start(self, incident: Incident, budget: AgentBudget) -> AgentState:
        state = AgentState(run_id=uuid4(), incident=incident, budget=budget)
        self.store.create(state)
        return await self._invoke(state)

    async def resume(self, run_id: UUID) -> AgentState:
        state = self.store.load(run_id)
        if state is None:
            raise KeyError(f"agent run {run_id} does not exist")
        if state.next_node == AgentNode.END:
            return state
        state.status = AgentRunStatus.RUNNING
        state.stop_reason = None
        state.updated_at = utc_now()
        self.store.save(state)
        return await self._invoke(state)

    async def _invoke(self, state: AgentState) -> AgentState:
        result = await self.graph.ainvoke({"state": state})
        final = result["state"]
        if not isinstance(final, AgentState):
            final = AgentState.model_validate(final)
        if self.interrupt_after and final.next_node != AgentNode.END:
            final.status = AgentRunStatus.PAUSED
            final.stop_reason = f"paused after {self.interrupt_after[-1].value}"
            final.updated_at = utc_now()
            self.store.save(final)
        return final

    def _entry_router(self, payload: GraphPayload) -> str:
        return payload["state"].next_node.value

    def _next_router(self, payload: GraphPayload) -> str:
        return payload["state"].next_node.value

    def _copy(self, payload: GraphPayload) -> AgentState:
        return payload["state"].model_copy(deep=True)

    def _checkpoint(self, state: AgentState, next_node: AgentNode) -> GraphPayload:
        state.next_node = next_node
        state.updated_at = utc_now()
        self.store.save(state)
        return {"state": state}

    def _mark_exhausted(self, state: AgentState, reason: str) -> None:
        state.budget.exhausted_reason = reason
        state.stop_reason = reason
        state.status = AgentRunStatus.BUDGET_EXHAUSTED

    def _budget_reason(self, state: AgentState) -> str | None:
        budget = state.budget
        elapsed = (utc_now() - state.started_at).total_seconds()
        if elapsed > budget.time_limit_seconds:
            return f"time limit exceeded ({budget.time_limit_seconds:g}s)"
        if budget.steps_used >= budget.max_steps:
            return f"step budget exhausted ({budget.max_steps})"
        if budget.tool_calls_used >= budget.max_tool_calls:
            return f"tool-call budget exhausted ({budget.max_tool_calls})"
        if budget.token_budget > 0 and budget.tokens_used > budget.token_budget:
            return f"token budget exhausted ({budget.token_budget})"
        if budget.cost_budget > 0 and budget.cost_used > budget.cost_budget:
            return f"cost budget exhausted ({budget.cost_budget:g})"
        return None

    def _apply_usage(self, state: AgentState, usage: ProviderUsage) -> bool:
        state.budget.tokens_used += usage.total_tokens
        state.budget.cost_used += usage.estimated_cost
        reason = self._budget_reason(state)
        if reason is not None:
            self._mark_exhausted(state, reason)
            return False
        return True

    def _provider_failure(self, state: AgentState, exc: ReasoningProviderError) -> None:
        state.status = AgentRunStatus.FAILED
        state.stop_reason = str(exc)

    async def _triage(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        state.status = AgentRunStatus.RUNNING
        state.stop_reason = None
        return self._checkpoint(state, AgentNode.PLAN)

    async def _plan(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        try:
            plan, usage = await self.provider.plan(state)
        except ReasoningProviderError as exc:
            self._provider_failure(state, exc)
            return self._checkpoint(state, AgentNode.REPORT)
        state.plan = plan
        if not self._apply_usage(state, usage):
            return self._checkpoint(state, AgentNode.REPORT)
        return self._checkpoint(state, AgentNode.SELECT_TOOL)

    async def _select_tool(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        reason = self._budget_reason(state)
        if reason is not None:
            self._mark_exhausted(state, reason)
            return self._checkpoint(state, AgentNode.REPORT)
        state.budget.steps_used += 1
        if state.plan is None:
            state.status = AgentRunStatus.FAILED
            state.stop_reason = "investigation plan is missing"
            return self._checkpoint(state, AgentNode.REPORT)
        step = next((item for item in state.plan.steps if not item.completed), None)
        if step is None:
            state.pending_tool = None
            return self._checkpoint(state, AgentNode.DIAGNOSE)
        invocation = ToolInvocation(tool=step.tool, arguments=step.arguments)
        signature = json.dumps(invocation.model_dump(mode="json"), sort_keys=True)
        repeats = state.budget.repeated_calls.get(signature, 0)
        if repeats >= state.budget.max_repeated_identical_calls:
            self._mark_exhausted(
                state,
                "repeated identical tool-call budget exhausted "
                f"({state.budget.max_repeated_identical_calls})",
            )
            return self._checkpoint(state, AgentNode.REPORT)
        state.pending_tool = invocation
        return self._checkpoint(state, AgentNode.EXECUTE_TOOL)

    async def _execute_tool(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        invocation = state.pending_tool
        if invocation is None:
            state.status = AgentRunStatus.FAILED
            state.stop_reason = "execute_tool reached without a pending tool invocation"
            return self._checkpoint(state, AgentNode.REPORT)
        signature = json.dumps(invocation.model_dump(mode="json"), sort_keys=True)
        state.budget.repeated_calls[signature] = state.budget.repeated_calls.get(signature, 0) + 1
        state.budget.tool_calls_used += 1
        response = await self.registry.invoke(invocation)
        state.pending_response = response
        state.tool_history.append(
            ToolCall(
                tool_name=invocation.tool,
                arguments=invocation.arguments,
                started_at=response.started_at,
                completed_at=response.completed_at,
                status=response.status,
                result_reference=None,
                risk_level=response.risk_level,
            )
        )
        if state.plan is not None:
            for step in state.plan.steps:
                if not step.completed and step.tool == invocation.tool and step.arguments == invocation.arguments:
                    step.completed = True
                    break
        return self._checkpoint(state, AgentNode.STORE_EVIDENCE)

    async def _store_evidence(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        response = state.pending_response
        invocation = state.pending_tool
        if response is not None and invocation is not None and response.data is not None:
            raw_reference = json.dumps(
                {
                    "tool": invocation.tool,
                    "arguments": invocation.arguments,
                    "payload": response.data.payload,
                    "truncated": response.data.truncated,
                },
                default=str,
                sort_keys=True,
            )
            evidence = Evidence(
                incident_id=state.incident.id,
                source=response.data.source,
                evidence_type=response.data.evidence_type,
                service=response.data.service,
                timestamp=response.data.captured_at,
                observation=(
                    f"{invocation.tool} returned observable "
                    f"{response.data.evidence_type.value} evidence"
                ),
                raw_reference=raw_reference,
                reliability=1.0,
            )
            state.evidence.append(evidence)
            if state.tool_history:
                state.tool_history[-1].result_reference = str(evidence.id)
        state.pending_response = None
        state.pending_tool = None
        return self._checkpoint(state, AgentNode.UPDATE_HYPOTHESIS)

    async def _update_hypothesis(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        try:
            candidates, usage = await self.provider.update_hypotheses(state)
        except ReasoningProviderError as exc:
            self._provider_failure(state, exc)
            return self._checkpoint(state, AgentNode.REPORT)
        merged: dict[str, Hypothesis] = {item.root_cause_code: item for item in state.hypotheses}
        for candidate in candidates:
            previous = merged.get(candidate.root_cause_code)
            if previous is not None:
                candidate.id = previous.id
            merged[candidate.root_cause_code] = candidate
        state.hypotheses = sorted(merged.values(), key=lambda item: item.confidence, reverse=True)
        if state.hypotheses:
            state.current_hypothesis = state.hypotheses[0].id
            state.confidence = state.hypotheses[0].confidence
        if not self._apply_usage(state, usage):
            return self._checkpoint(state, AgentNode.REPORT)
        return self._checkpoint(state, AgentNode.ENOUGH_EVIDENCE)

    async def _enough_evidence(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        try:
            enough, usage = await self.provider.enough_evidence(state)
        except ReasoningProviderError as exc:
            self._provider_failure(state, exc)
            return self._checkpoint(state, AgentNode.REPORT)
        if not self._apply_usage(state, usage):
            return self._checkpoint(state, AgentNode.REPORT)
        no_remaining_steps = bool(state.plan) and all(item.completed for item in state.plan.steps)
        if enough or no_remaining_steps:
            return self._checkpoint(state, AgentNode.DIAGNOSE)
        reason = self._budget_reason(state)
        if reason is not None:
            self._mark_exhausted(state, reason)
            return self._checkpoint(state, AgentNode.REPORT)
        return self._checkpoint(state, AgentNode.SELECT_TOOL)

    async def _diagnose(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        try:
            code, diagnosis, usage = await self.provider.diagnose(state)
        except ReasoningProviderError as exc:
            self._provider_failure(state, exc)
            return self._checkpoint(state, AgentNode.REPORT)
        state.diagnosis_code = code
        state.final_diagnosis = diagnosis
        state.confidence = diagnosis.confidence
        if not self._apply_usage(state, usage):
            return self._checkpoint(state, AgentNode.REPORT)
        return self._checkpoint(state, AgentNode.RECOMMEND)

    async def _recommend(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        try:
            action, usage = await self.provider.recommend(state)
        except ReasoningProviderError as exc:
            self._provider_failure(state, exc)
            return self._checkpoint(state, AgentNode.REPORT)
        state.proposed_action = action
        if state.final_diagnosis is not None and action is not None:
            state.final_diagnosis.recommended_actions = [action.description]
        if not self._apply_usage(state, usage):
            return self._checkpoint(state, AgentNode.REPORT)
        return self._checkpoint(state, AgentNode.REPORT)

    async def _report(self, payload: GraphPayload) -> GraphPayload:
        state = self._copy(payload)
        diagnosis = state.final_diagnosis
        if diagnosis is None:
            diagnosis = Diagnosis(
                primary_root_cause="Investigation stopped before a primary root cause could be established.",
                confidence=state.confidence,
                evidence_ids=[item.id for item in state.evidence],
                recommended_actions=[],
            )
            state.final_diagnosis = diagnosis
            if state.diagnosis_code is None:
                state.diagnosis_code = "inconclusive"
        if state.status == AgentRunStatus.RUNNING:
            if diagnosis.evidence_ids:
                state.status = AgentRunStatus.COMPLETED
            else:
                state.status = AgentRunStatus.FAILED
                state.stop_reason = "investigation ended without supporting evidence"
        state.verification = VerificationResult(
            status=VerificationStatus.NOT_RUN,
            summary=(
                "Phase 4 recommends remediation but does not execute it; active "
                "verification and approval are deferred to Phase 5."
            ),
            evidence_ids=[],
        )
        claims: list[GroundedClaim] = []
        if diagnosis.evidence_ids:
            claims.append(
                GroundedClaim(
                    statement=diagnosis.primary_root_cause,
                    evidence_ids=diagnosis.evidence_ids,
                )
            )
        state.report = AgentReport(
            run_id=state.run_id,
            status=state.status,
            root_cause_code=state.diagnosis_code or "inconclusive",
            diagnosis=diagnosis,
            claims=claims,
            proposed_action=state.proposed_action,
            verification=state.verification,
        )
        return self._checkpoint(state, AgentNode.END)
