from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.agent.models import AgentState
from app.persistence.models import (
    AgentCheckpointRecord,
    AgentRunRecord,
    DiagnosisRecord,
    EvidenceRecord,
    HypothesisRecord,
    IncidentRecord,
    ToolCallRecord,
)
from app.persistence.session import create_session_factory


class AgentStore(Protocol):
    def create(self, state: AgentState) -> None: ...

    def save(self, state: AgentState) -> None: ...

    def load(self, run_id: UUID) -> AgentState | None: ...


class InMemoryAgentStore:
    def __init__(self) -> None:
        self._states: dict[UUID, AgentState] = {}

    def create(self, state: AgentState) -> None:
        if state.run_id in self._states:
            raise ValueError(f"agent run {state.run_id} already exists")
        self.save(state)

    def save(self, state: AgentState) -> None:
        self._states[state.run_id] = state.model_copy(deep=True)

    def load(self, run_id: UUID) -> AgentState | None:
        state = self._states.get(run_id)
        return state.model_copy(deep=True) if state is not None else None


class SqlAgentStore:
    def __init__(
        self,
        engine: Engine,
        *,
        architecture_version: str,
        model: str,
    ) -> None:
        self.session_factory: sessionmaker[Session] = create_session_factory(engine)
        self.architecture_version = architecture_version
        self.model = model

    def create(self, state: AgentState) -> None:
        with self.session_factory() as session:
            if session.get(AgentRunRecord, str(state.run_id)) is not None:
                raise ValueError(f"agent run {state.run_id} already exists")
        self.save(state)

    def save(self, state: AgentState) -> None:
        with self.session_factory() as session:
            session.merge(
                IncidentRecord(
                    id=str(state.incident.id),
                    title=state.incident.title,
                    description=state.incident.description,
                    severity=state.incident.severity.value,
                    service=state.incident.service,
                    start_time=state.incident.start_time,
                    status=state.incident.status.value,
                    scenario_id=state.incident.scenario_id,
                )
            )
            session.merge(
                AgentRunRecord(
                    id=str(state.run_id),
                    incident_id=str(state.incident.id),
                    architecture_version=self.architecture_version,
                    model=self.model,
                    step_count=state.budget.steps_used,
                    tool_call_count=state.budget.tool_calls_used,
                    token_usage=state.budget.tokens_used,
                    estimated_cost=state.budget.cost_used,
                    status=state.status.value,
                )
            )
            for item in state.evidence:
                session.merge(
                    EvidenceRecord(
                        id=str(item.id),
                        incident_id=str(item.incident_id),
                        run_id=str(state.run_id),
                        source=item.source,
                        evidence_type=item.evidence_type.value,
                        service=item.service,
                        timestamp=item.timestamp,
                        observation=item.observation,
                        raw_reference=item.raw_reference,
                        reliability=item.reliability,
                    )
                )
            for item in state.hypotheses:
                session.merge(
                    HypothesisRecord(
                        id=str(item.id),
                        run_id=str(state.run_id),
                        description=item.description,
                        root_cause_code=item.root_cause_code,
                        confidence=item.confidence,
                        supporting_evidence=[str(value) for value in item.supporting_evidence],
                        contradicting_evidence=[str(value) for value in item.contradicting_evidence],
                        first_possible_cause_time=item.first_possible_cause_time,
                        effect_time=item.effect_time,
                        status=item.status.value,
                    )
                )
            for item in state.tool_history:
                session.merge(
                    ToolCallRecord(
                        id=str(item.id),
                        run_id=str(state.run_id),
                        tool_name=item.tool_name,
                        arguments=item.arguments,
                        started_at=item.started_at,
                        completed_at=item.completed_at,
                        status=item.status.value,
                        result_reference=item.result_reference,
                        risk_level=item.risk_level.value,
                    )
                )
            if state.final_diagnosis is not None:
                diagnosis = state.final_diagnosis
                session.merge(
                    DiagnosisRecord(
                        id=str(state.run_id),
                        run_id=str(state.run_id),
                        primary_root_cause=diagnosis.primary_root_cause,
                        secondary_root_causes=diagnosis.secondary_root_causes,
                        confidence=diagnosis.confidence,
                        evidence_ids=[str(value) for value in diagnosis.evidence_ids],
                        recommended_actions=diagnosis.recommended_actions,
                        verification_status=diagnosis.verification_status.value,
                    )
                )
            checkpoint = session.get(AgentCheckpointRecord, str(state.run_id))
            revision = 1 if checkpoint is None else checkpoint.revision + 1
            session.merge(
                AgentCheckpointRecord(
                    run_id=str(state.run_id),
                    state=state.model_dump(mode="json"),
                    next_node=state.next_node.value,
                    revision=revision,
                    updated_at=state.updated_at,
                )
            )
            session.commit()

    def load(self, run_id: UUID) -> AgentState | None:
        with self.session_factory() as session:
            checkpoint = session.get(AgentCheckpointRecord, str(run_id))
            if checkpoint is None:
                return None
            return AgentState.model_validate(checkpoint.state)
