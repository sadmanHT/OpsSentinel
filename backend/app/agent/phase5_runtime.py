from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from app.agent.models import (
    AgentBudget,
    AgentNode,
    AgentReport,
    AgentState,
    ApprovalDecision,
    ApprovalRequest,
    OperationStage,
    ProposedAction,
    ToolFailureRecord,
    VerificationResult,
)
from app.agent.providers import ReasoningProvider
from app.agent.runtime import AgentRuntime
from app.agent.store import AgentStore
from app.mcp.models import ToolInvocation, ToolResponse
from app.mcp.registry import ToolRegistry
from app.mcp.retrying import RetryingToolRegistry
from app.models.domain import (
    AgentRunStatus,
    Evidence,
    Incident,
    RiskLevel,
    ToolCall,
    ToolCallStatus,
    VerificationStatus,
    utc_now,
)


class Phase5Runtime:
    """Operational control plane layered on top of the validated Phase 4 investigator."""

    architecture_version = "phase5-safe-operational-agent-v1"

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
        self.investigation = AgentRuntime(
            registry=registry,
            provider=provider,
            store=store,
            interrupt_after=interrupt_after,
        )

    async def start(
        self,
        incident: Incident,
        budget: AgentBudget,
        *,
        operational_mode: bool = False,
    ) -> AgentState:
        self._begin_retry_capture()
        state = await self.investigation.start(incident, budget)
        state.operational_mode = operational_mode
        self._capture_retry_events(state)
        if operational_mode and state.status == AgentRunStatus.COMPLETED:
            state.operation_stage = OperationStage.ASSESS_ACTION
            state.updated_at = utc_now()
            self.store.save(state)
            return await self._continue_operation(state)
        self.store.save(state)
        return state

    async def resume(self, run_id: UUID) -> AgentState:
        state = self.store.load(run_id)
        if state is None:
            raise KeyError(f"agent run {run_id} does not exist")
        self._begin_retry_capture()

        if state.operational_mode:
            if (
                state.operation_stage == OperationStage.WAIT_APPROVAL
                and state.approval is not None
                and state.approval.decision == ApprovalDecision.PENDING
            ):
                return state
            if state.operation_stage in {
                OperationStage.ASSESS_ACTION,
                OperationStage.EXECUTE_ACTION,
                OperationStage.VERIFY,
            }:
                return await self._continue_operation(state)
            if state.operation_stage == OperationStage.COMPLETE:
                return state

        if state.next_node != AgentNode.END:
            state = await self.investigation.resume(run_id)
            self._capture_retry_events(state)
            self.store.save(state)
            if state.operational_mode and state.status == AgentRunStatus.COMPLETED:
                state.operation_stage = OperationStage.ASSESS_ACTION
                state.updated_at = utc_now()
                self.store.save(state)
                return await self._continue_operation(state)
            return state

        if state.operational_mode and state.operation_stage == OperationStage.NONE:
            state.operation_stage = OperationStage.ASSESS_ACTION
            state.updated_at = utc_now()
            self.store.save(state)
            return await self._continue_operation(state)
        return state

    async def decide_approval(
        self,
        run_id: UUID,
        *,
        decision: ApprovalDecision,
        actor: str,
    ) -> AgentState:
        state = self.store.load(run_id)
        if state is None:
            raise KeyError(f"agent run {run_id} does not exist")
        self._begin_retry_capture()
        approval = state.approval
        if (
            not state.operational_mode
            or state.operation_stage != OperationStage.WAIT_APPROVAL
            or approval is None
        ):
            raise ValueError("agent run is not waiting for an approval decision")
        if approval.decision != ApprovalDecision.PENDING:
            raise ValueError("approval has already been decided")
        if decision == ApprovalDecision.PENDING:
            raise ValueError("approval decision must be terminal")

        approval.decision = decision
        approval.decided_at = utc_now()
        approval.decided_by = actor
        state.updated_at = approval.decided_at
        state.stop_reason = None

        if decision == ApprovalDecision.APPROVED:
            state.status = AgentRunStatus.RUNNING
            state.operation_stage = OperationStage.EXECUTE_ACTION
            self.store.save(state)
            return await self._continue_operation(state)

        state.status = AgentRunStatus.COMPLETED
        state.operation_stage = OperationStage.COMPLETE
        state.verification = VerificationResult(
            status=VerificationStatus.NOT_RUN,
            summary=f"Proposed action was {decision.value}; no operational change was executed.",
        )
        state.stop_reason = f"human approval {decision.value}"
        if state.final_diagnosis is not None:
            state.final_diagnosis.verification_status = VerificationStatus.NOT_RUN
        self._refresh_report(state)
        self.store.save(state)
        return state

    async def _continue_operation(self, state: AgentState) -> AgentState:
        while True:
            if state.operation_stage == OperationStage.ASSESS_ACTION:
                state = self._assess_action(state)
                if state.operation_stage in {
                    OperationStage.WAIT_APPROVAL,
                    OperationStage.COMPLETE,
                }:
                    return state
                continue
            if state.operation_stage == OperationStage.EXECUTE_ACTION:
                state = await self._execute_action(state)
                if state.operation_stage == OperationStage.COMPLETE:
                    return state
                continue
            if state.operation_stage == OperationStage.VERIFY:
                return await self._verify(state)
            return state

    def _assess_action(self, state: AgentState) -> AgentState:
        action = state.proposed_action
        if action is None:
            state.operation_stage = OperationStage.COMPLETE
            state.status = AgentRunStatus.COMPLETED
            state.stop_reason = "no operational action was proposed"
            self._refresh_report(state)
            self.store.save(state)
            return state

        action = self._enrich_action(state, action)
        state.proposed_action = action
        if state.final_diagnosis is not None:
            state.final_diagnosis.recommended_actions = [action.description]

        if action.tool is None:
            state.operation_stage = OperationStage.COMPLETE
            state.status = AgentRunStatus.COMPLETED
            state.stop_reason = "proposed action has no executable sandbox operation"
            self._refresh_report(state)
            self.store.save(state)
            return state

        if action.risk_level == RiskLevel.R3:
            state.failures.append(
                ToolFailureRecord(
                    tool=action.tool,
                    code="r3_blocked",
                    message="R3 destructive operations are prohibited by policy.",
                    retryable=False,
                    attempt=1,
                )
            )
            state.verification = VerificationResult(
                status=VerificationStatus.NOT_RUN,
                summary="R3 action was blocked before execution; verification was not required.",
            )
            state.operation_stage = OperationStage.COMPLETE
            state.status = AgentRunStatus.COMPLETED
            state.stop_reason = "R3 action blocked by safety policy"
            self._refresh_report(state)
            self.store.save(state)
            return state

        if action.risk_level == RiskLevel.R2:
            if state.approval is None:
                state.approval = ApprovalRequest(
                    action=action,
                    why_proposed=action.rationale,
                    evidence_ids=action.evidence_ids,
                    expected_benefit=action.expected_benefit,
                    possible_risk=action.possible_risk,
                    rollback_strategy=action.rollback_strategy,
                )
            state.operation_stage = OperationStage.WAIT_APPROVAL
            state.status = AgentRunStatus.PAUSED
            state.stop_reason = "awaiting human approval for R2 sandbox action"
            state.updated_at = utc_now()
            self._refresh_report(state)
            self.store.save(state)
            return state

        state.operation_stage = OperationStage.EXECUTE_ACTION
        state.status = AgentRunStatus.RUNNING
        state.stop_reason = None
        state.updated_at = utc_now()
        self.store.save(state)
        return state

    def _enrich_action(self, state: AgentState, action: ProposedAction) -> ProposedAction:
        if action.tool is not None:
            return action
        service = state.incident.service
        if service not in {"gateway", "checkout", "inventory", "payment", "worker"}:
            return action
        return action.model_copy(
            update={
                "tool": "rollback_sandbox_deployment",
                "arguments": {"service": service},
                "expected_benefit": (
                    f"Restore {service} to the simulator baseline and remove the diagnosed fault."
                ),
                "possible_risk": (
                    f"Rollback may interrupt in-flight sandbox requests to {service}."
                ),
                "rollback_strategy": (
                    "The benchmark harness can deterministically reinject the scenario if the "
                    "operational change must be reversed for further testing."
                ),
            }
        )

    async def _execute_action(self, state: AgentState) -> AgentState:
        action = state.proposed_action
        if action is None or action.tool is None:
            state.operation_stage = OperationStage.COMPLETE
            state.status = AgentRunStatus.FAILED
            state.stop_reason = "execute action reached without an executable action"
            self.store.save(state)
            return state

        if state.budget.tool_calls_used >= state.budget.max_tool_calls:
            state.status = AgentRunStatus.BUDGET_EXHAUSTED
            state.budget.exhausted_reason = "tool-call budget exhausted before operational action"
            state.stop_reason = state.budget.exhausted_reason
            state.operation_stage = OperationStage.COMPLETE
            self._refresh_report(state)
            self.store.save(state)
            return state

        approval_id: str | None = None
        if action.risk_level == RiskLevel.R2:
            approval = state.approval
            if approval is None or approval.decision != ApprovalDecision.APPROVED:
                state.status = AgentRunStatus.PAUSED
                state.operation_stage = OperationStage.WAIT_APPROVAL
                state.stop_reason = "R2 action cannot execute without an approved request"
                self.store.save(state)
                return state
            approval_id = str(approval.id)

        invocation = ToolInvocation(tool=action.tool, arguments=action.arguments)
        response = await self.registry.invoke(
            invocation,
            trusted_approval_id=approval_id,
        )
        retry_events = self._capture_retry_events(state)
        attempts = retry_events + (1 if response.status == ToolCallStatus.SUCCEEDED else 0)
        state.budget.tool_calls_used += max(1, attempts)
        state.budget.steps_used += 1
        state.action_response = response
        call = self._append_tool_call(state, invocation, response)
        if response.data is not None:
            evidence = self._evidence_from_response(state, invocation, response)
            state.evidence.append(evidence)
            call.result_reference = str(evidence.id)

        if response.status != ToolCallStatus.SUCCEEDED:
            state.verification = VerificationResult(
                status=VerificationStatus.INCONCLUSIVE,
                summary=(
                    "Approved action did not complete successfully; post-action verification "
                    "was skipped."
                ),
            )
            state.operation_stage = OperationStage.COMPLETE
            state.status = AgentRunStatus.FAILED
            state.stop_reason = "approved sandbox action failed or was blocked"
            if state.final_diagnosis is not None:
                state.final_diagnosis.verification_status = VerificationStatus.INCONCLUSIVE
            self._refresh_report(state)
            self.store.save(state)
            return state

        state.operation_stage = OperationStage.VERIFY
        state.status = AgentRunStatus.RUNNING
        state.stop_reason = None
        state.updated_at = utc_now()
        self.store.save(state)
        return state

    async def _verify(self, state: AgentState) -> AgentState:
        invocation = self._verification_invocation(state)
        response = await self.registry.invoke(invocation)
        retry_events = self._capture_retry_events(state)
        attempts = retry_events + (1 if response.status == ToolCallStatus.SUCCEEDED else 0)
        state.budget.tool_calls_used += max(1, attempts)
        state.budget.steps_used += 1
        call = self._append_tool_call(state, invocation, response)

        evidence_ids: list[UUID] = []
        passed: bool | None = None
        if response.data is not None:
            evidence = self._evidence_from_response(state, invocation, response)
            state.evidence.append(evidence)
            evidence_ids.append(evidence.id)
            call.result_reference = str(evidence.id)
            payload = response.data.payload
            if isinstance(payload, dict) and isinstance(payload.get("passed"), bool):
                passed = payload["passed"]

        if response.status != ToolCallStatus.SUCCEEDED:
            verification_status = VerificationStatus.INCONCLUSIVE
            summary = "Deterministic verification tool failed; remediation outcome is inconclusive."
        elif passed is True:
            verification_status = VerificationStatus.PASSED
            summary = "Deterministic post-action verification passed against live simulator state."
        elif passed is False:
            verification_status = VerificationStatus.FAILED
            summary = (
                "Deterministic post-action verification completed but the expected healthy state "
                "was not observed."
            )
        else:
            verification_status = VerificationStatus.INCONCLUSIVE
            summary = "Verification completed without a deterministic pass/fail signal."

        state.verification = VerificationResult(
            status=verification_status,
            summary=summary,
            evidence_ids=evidence_ids,
        )
        if state.final_diagnosis is not None:
            state.final_diagnosis.verification_status = verification_status
        state.operation_stage = OperationStage.COMPLETE
        state.status = AgentRunStatus.COMPLETED
        state.stop_reason = None if verification_status == VerificationStatus.PASSED else summary
        state.updated_at = utc_now()
        self._refresh_report(state)
        self.store.save(state)
        return state

    def _verification_invocation(self, state: AgentState) -> ToolInvocation:
        service = state.incident.service
        code = (state.diagnosis_code or "").casefold()
        if "n_plus_one" in code or "n+1" in code:
            return ToolInvocation(
                tool="rerun_load_test",
                arguments={"profile": "normal", "path": "/checkout"},
            )
        if service == "inventory":
            return ToolInvocation(
                tool="reproduce_request",
                arguments={
                    "service": "inventory",
                    "method": "GET",
                    "path": "/inventory/SKU-RED",
                    "expected_status": 200,
                },
            )
        if service == "worker":
            return ToolInvocation(
                tool="reproduce_request",
                arguments={
                    "service": "worker",
                    "method": "POST",
                    "path": "/work",
                    "expected_status": 200,
                },
            )
        if service == "payment":
            return ToolInvocation(
                tool="reproduce_request",
                arguments={
                    "service": "gateway",
                    "method": "GET",
                    "path": "/checkout",
                    "expected_status": 200,
                },
            )
        if service == "checkout":
            return ToolInvocation(
                tool="reproduce_request",
                arguments={
                    "service": "checkout",
                    "method": "GET",
                    "path": "/orders",
                    "expected_status": 200,
                },
            )
        return ToolInvocation(
            tool="reproduce_request",
            arguments={
                "service": "gateway",
                "method": "GET",
                "path": "/health",
                "expected_status": 200,
            },
        )

    def _append_tool_call(
        self,
        state: AgentState,
        invocation: ToolInvocation,
        response: ToolResponse,
    ) -> ToolCall:
        call = ToolCall(
            tool_name=invocation.tool,
            arguments=invocation.arguments,
            started_at=response.started_at,
            completed_at=response.completed_at,
            status=response.status,
            result_reference=None,
            risk_level=response.risk_level,
        )
        state.tool_history.append(call)
        return call

    def _evidence_from_response(
        self,
        state: AgentState,
        invocation: ToolInvocation,
        response: ToolResponse,
    ) -> Evidence:
        assert response.data is not None
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
        return Evidence(
            incident_id=state.incident.id,
            source=response.data.source,
            evidence_type=response.data.evidence_type,
            service=response.data.service,
            timestamp=response.data.captured_at,
            observation=f"{invocation.tool} returned deterministic operational evidence",
            raw_reference=raw_reference,
            reliability=1.0,
        )

    def _begin_retry_capture(self) -> None:
        if isinstance(self.registry, RetryingToolRegistry):
            self.registry.begin_capture()

    def _capture_retry_events(self, state: AgentState) -> int:
        if not isinstance(self.registry, RetryingToolRegistry):
            return 0
        events = self.registry.drain_failures()
        for event in events:
            state.failures.append(
                ToolFailureRecord(
                    tool=event.tool,
                    code=event.code,
                    message=event.message,
                    retryable=event.retryable,
                    attempt=event.attempt,
                )
            )
            state.retry_counts[event.tool] = state.retry_counts.get(event.tool, 0) + 1
        return len(events)

    def _refresh_report(self, state: AgentState) -> None:
        if state.report is None or state.final_diagnosis is None or not state.diagnosis_code:
            return
        state.report = AgentReport(
            run_id=state.run_id,
            status=state.status,
            root_cause_code=state.diagnosis_code,
            diagnosis=state.final_diagnosis,
            claims=state.report.claims,
            proposed_action=state.proposed_action,
            verification=state.verification,
            generated_at=utc_now(),
        )
