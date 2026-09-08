from __future__ import annotations

from app.agent.models import (
    AgentState,
    InvestigationPlan,
    PlanStep,
    ProposedAction,
    ProviderUsage,
)
from app.agent.providers import ReasoningProvider
from app.models.domain import Diagnosis, Hypothesis

COMPOUND_EVIDENCE_PROVIDER_MARKER = "compound-evidence-plan-v1"
UNRESOLVED_EVIDENCE_PROVIDER_MARKER = "unresolved-evidence-stop-v1"


class CompoundEvidencePlanProvider:
    """Use one ground-truth-blind cross-service plan for H5 compound trials."""

    def __init__(self, inner: ReasoningProvider) -> None:
        self.inner = inner
        self.name = f"{inner.name}+{COMPOUND_EVIDENCE_PROVIDER_MARKER}"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        steps = [
            PlanStep(
                id="checkout-db-query-count",
                objective="Measure checkout database query fan-out.",
                tool="query_metrics",
                arguments={"service": "checkout", "metric": "db_query_count"},
                rationale="Check for an N+1-style checkout regression.",
            ),
            PlanStep(
                id="checkout-request-logs",
                objective="Inspect checkout request logs.",
                tool="search_logs",
                arguments={"service": "checkout", "query": "/orders", "limit": 20},
                rationale="Corroborate checkout query fan-out with request evidence.",
            ),
            PlanStep(
                id="inventory-db-connections",
                objective="Measure inventory database connections.",
                tool="query_metrics",
                arguments={"service": "inventory", "metric": "db_connections"},
                rationale="Check for inventory connection-capacity exhaustion.",
            ),
            PlanStep(
                id="inventory-errors",
                objective="Inspect inventory errors.",
                tool="search_logs",
                arguments={"service": "inventory", "level": "ERROR", "limit": 20},
                rationale="Corroborate inventory connection pressure with failures.",
            ),
            PlanStep(
                id="worker-disk",
                objective="Measure worker disk utilization.",
                tool="query_metrics",
                arguments={"service": "worker", "metric": "disk_usage"},
                rationale="Check for worker disk exhaustion.",
            ),
            PlanStep(
                id="worker-memory",
                objective="Measure worker memory utilization.",
                tool="query_metrics",
                arguments={"service": "worker", "metric": "memory_usage"},
                rationale="Check for worker memory pressure.",
            ),
            PlanStep(
                id="worker-restarts",
                objective="Measure worker container restarts.",
                tool="query_metrics",
                arguments={"service": "worker", "metric": "container_restarts"},
                rationale="Corroborate memory pressure with restart behavior.",
            ),
            PlanStep(
                id="worker-errors",
                objective="Inspect worker errors.",
                tool="search_logs",
                arguments={"service": "worker", "level": "ERROR", "limit": 20},
                rationale="Distinguish worker disk and memory failure signatures.",
            ),
            PlanStep(
                id="payment-warnings",
                objective="Inspect payment authentication/configuration warnings.",
                tool="search_logs",
                arguments={"service": "payment", "level": "WARNING", "limit": 20},
                rationale="Check for a broken payment configuration.",
            ),
            PlanStep(
                id="gateway-errors",
                objective="Inspect gateway dependency failures.",
                tool="search_logs",
                arguments={"service": "gateway", "level": "ERROR", "limit": 20},
                rationale="Corroborate payment failures at the upstream boundary.",
            ),
        ]
        return (
            InvestigationPlan(
                summary=(
                    "Inspect the same fixed cross-service passive evidence surface before "
                    "attributing a compound incident."
                ),
                steps=steps,
            ),
            ProviderUsage(),
        )

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


class UnresolvedEvidenceStoppingProvider:
    """Prevent an H5 diagnosis while required planned evidence remains unresolved."""

    def __init__(self, inner: ReasoningProvider) -> None:
        self.inner = inner
        self.name = f"{inner.name}+{UNRESOLVED_EVIDENCE_PROVIDER_MARKER}"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        return await self.inner.plan(state)

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        return await self.inner.update_hypotheses(state)

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        enough, usage = await self.inner.enough_evidence(state)
        plan = state.plan
        all_required_complete = plan is not None and all(
            step.completed for step in plan.steps if step.required
        )
        return enough and all_required_complete, usage

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        return await self.inner.diagnose(state)

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        return await self.inner.recommend(state)
