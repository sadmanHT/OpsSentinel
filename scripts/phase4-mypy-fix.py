from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}: {old!r}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "backend/app/agent/store.py",
    '''            for item in state.evidence:\n                session.merge(\n                    EvidenceRecord(\n                        id=str(item.id),\n                        incident_id=str(item.incident_id),\n                        run_id=str(state.run_id),\n                        source=item.source,\n                        evidence_type=item.evidence_type.value,\n                        service=item.service,\n                        timestamp=item.timestamp,\n                        observation=item.observation,\n                        raw_reference=item.raw_reference,\n                        reliability=item.reliability,\n                    )\n                )\n            for item in state.hypotheses:\n                session.merge(\n                    HypothesisRecord(\n                        id=str(item.id),\n                        run_id=str(state.run_id),\n                        description=item.description,\n                        root_cause_code=item.root_cause_code,\n                        confidence=item.confidence,\n                        supporting_evidence=[str(value) for value in item.supporting_evidence],\n                        contradicting_evidence=[\n                            str(value) for value in item.contradicting_evidence\n                        ],\n                        first_possible_cause_time=item.first_possible_cause_time,\n                        effect_time=item.effect_time,\n                        status=item.status.value,\n                    )\n                )\n            for item in state.tool_history:\n                session.merge(\n                    ToolCallRecord(\n                        id=str(item.id),\n                        run_id=str(state.run_id),\n                        tool_name=item.tool_name,\n                        arguments=item.arguments,\n                        started_at=item.started_at,\n                        completed_at=item.completed_at,\n                        status=item.status.value,\n                        result_reference=item.result_reference,\n                        risk_level=item.risk_level.value,\n                    )\n                )\n''',
    '''            for evidence in state.evidence:\n                session.merge(\n                    EvidenceRecord(\n                        id=str(evidence.id),\n                        incident_id=str(evidence.incident_id),\n                        run_id=str(state.run_id),\n                        source=evidence.source,\n                        evidence_type=evidence.evidence_type.value,\n                        service=evidence.service,\n                        timestamp=evidence.timestamp,\n                        observation=evidence.observation,\n                        raw_reference=evidence.raw_reference,\n                        reliability=evidence.reliability,\n                    )\n                )\n            for hypothesis in state.hypotheses:\n                session.merge(\n                    HypothesisRecord(\n                        id=str(hypothesis.id),\n                        run_id=str(state.run_id),\n                        description=hypothesis.description,\n                        root_cause_code=hypothesis.root_cause_code,\n                        confidence=hypothesis.confidence,\n                        supporting_evidence=[\n                            str(value) for value in hypothesis.supporting_evidence\n                        ],\n                        contradicting_evidence=[\n                            str(value) for value in hypothesis.contradicting_evidence\n                        ],\n                        first_possible_cause_time=hypothesis.first_possible_cause_time,\n                        effect_time=hypothesis.effect_time,\n                        status=hypothesis.status.value,\n                    )\n                )\n            for tool_call in state.tool_history:\n                session.merge(\n                    ToolCallRecord(\n                        id=str(tool_call.id),\n                        run_id=str(state.run_id),\n                        tool_name=tool_call.tool_name,\n                        arguments=tool_call.arguments,\n                        started_at=tool_call.started_at,\n                        completed_at=tool_call.completed_at,\n                        status=tool_call.status.value,\n                        result_reference=tool_call.result_reference,\n                        risk_level=tool_call.risk_level.value,\n                    )\n                )\n''',
)

replace_once(
    "backend/app/agent/providers.py",
    '''        if top < 0.9:\n            all_done = bool(state.plan) and all(\n                step.completed for step in state.plan.steps if step.required\n            )\n            return bool(all_done), ProviderUsage()\n''',
    '''        if top < 0.9:\n            plan = state.plan\n            all_done = plan is not None and all(\n                step.completed for step in plan.steps if step.required\n            )\n            return all_done, ProviderUsage()\n''',
)

replace_once(
    "backend/app/agent/runtime.py",
    "from collections.abc import Sequence\nfrom typing import Any, TypedDict\n",
    "from collections.abc import Awaitable, Callable, Hashable, Sequence\n"
    "from typing import Any, TypedDict, cast\n",
)
replace_once(
    "backend/app/agent/runtime.py",
    '''class GraphPayload(TypedDict):\n    state: AgentState\n\n\nclass AgentRuntime:\n''',
    '''class GraphPayload(TypedDict):\n    state: AgentState\n\n\nGraphNode = Callable[[GraphPayload], Awaitable[GraphPayload]]\n\n\nclass AgentRuntime:\n''',
)
replace_once(
    "backend/app/agent/runtime.py",
    '''        builder = StateGraph(GraphPayload)\n        builder.add_node(AgentNode.TRIAGE.value, self._triage)\n        builder.add_node(AgentNode.PLAN.value, self._plan)\n        builder.add_node(AgentNode.SELECT_TOOL.value, self._select_tool)\n        builder.add_node(AgentNode.EXECUTE_TOOL.value, self._execute_tool)\n        builder.add_node(AgentNode.STORE_EVIDENCE.value, self._store_evidence)\n        builder.add_node(AgentNode.UPDATE_HYPOTHESIS.value, self._update_hypothesis)\n        builder.add_node(AgentNode.ENOUGH_EVIDENCE.value, self._enough_evidence)\n        builder.add_node(AgentNode.DIAGNOSE.value, self._diagnose)\n        builder.add_node(AgentNode.RECOMMEND.value, self._recommend)\n        builder.add_node(AgentNode.REPORT.value, self._report)\n\n        entry_mapping: dict[str, Any] = {\n''',
    '''        builder = StateGraph(GraphPayload)\n\n        def add_node(node: AgentNode, action: GraphNode) -> None:\n            # LangGraph's overloads do not currently accept async bound methods cleanly\n            # under strict mypy, so contain the third-party typing gap at this boundary.\n            builder.add_node(node.value, cast(Any, action))\n\n        add_node(AgentNode.TRIAGE, self._triage)\n        add_node(AgentNode.PLAN, self._plan)\n        add_node(AgentNode.SELECT_TOOL, self._select_tool)\n        add_node(AgentNode.EXECUTE_TOOL, self._execute_tool)\n        add_node(AgentNode.STORE_EVIDENCE, self._store_evidence)\n        add_node(AgentNode.UPDATE_HYPOTHESIS, self._update_hypothesis)\n        add_node(AgentNode.ENOUGH_EVIDENCE, self._enough_evidence)\n        add_node(AgentNode.DIAGNOSE, self._diagnose)\n        add_node(AgentNode.RECOMMEND, self._recommend)\n        add_node(AgentNode.REPORT, self._report)\n\n        entry_mapping: dict[Hashable, str] = {\n''',
)
replace_once(
    "backend/app/agent/runtime.py",
    '''        no_remaining_steps = bool(state.plan) and all(item.completed for item in state.plan.steps)\n        if enough or no_remaining_steps:\n''',
    '''        plan = state.plan\n        no_remaining_steps = plan is not None and all(item.completed for item in plan.steps)\n        if enough or no_remaining_steps:\n''',
)

print("Applied exact Phase 4 strict-mypy fixes")
