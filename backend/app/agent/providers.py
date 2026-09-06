from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.agent.models import (
    AgentState,
    InvestigationPlan,
    PlanStep,
    ProposedAction,
    ProviderUsage,
)
from app.models.domain import (
    Diagnosis,
    Evidence,
    Hypothesis,
    HypothesisStatus,
    RiskLevel,
)


class ReasoningProviderError(RuntimeError):
    pass


class ReasoningProvider(Protocol):
    name: str

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]: ...

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]: ...

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]: ...

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]: ...

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]: ...


def _record(evidence: Evidence) -> dict[str, Any]:
    if not evidence.raw_reference:
        return {}
    try:
        value = json.loads(evidence.raw_reference)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _payload(evidence: Evidence) -> Any:
    return _record(evidence).get("payload")


def _arguments(evidence: Evidence) -> dict[str, Any]:
    value = _record(evidence).get("arguments", {})
    return value if isinstance(value, dict) else {}


def _metric_evidence(
    evidence: Iterable[Evidence], service: str, metric: str
) -> tuple[float | None, UUID | None]:
    for item in reversed(list(evidence)):
        arguments = _arguments(item)
        if arguments.get("service") == service and arguments.get("metric") == metric:
            payload = _payload(item)
            if isinstance(payload, dict):
                value = payload.get("value")
                if isinstance(value, (int, float)):
                    return float(value), item.id
    return None, None


def _log_matches(
    evidence: Iterable[Evidence],
    *,
    service: str,
    status: int | None = None,
    field: str | None = None,
    minimum: float | None = None,
) -> list[UUID]:
    matches: list[UUID] = []
    for item in evidence:
        arguments = _arguments(item)
        if arguments.get("service") != service:
            continue
        payload = _payload(item)
        if not isinstance(payload, list):
            continue
        found = False
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            if status is not None and entry.get("status") == status:
                found = True
            if field is not None and minimum is not None:
                value = entry.get(field)
                if isinstance(value, (int, float)) and float(value) >= minimum:
                    found = True
        if found:
            matches.append(item.id)
    return matches


def _hypothesis(
    code: str,
    description: str,
    confidence: float,
    evidence_ids: list[UUID],
) -> Hypothesis:
    return Hypothesis(
        description=description,
        root_cause_code=code,
        confidence=confidence,
        supporting_evidence=evidence_ids,
        status=(
            HypothesisStatus.CONFIRMED
            if confidence >= 0.9
            else HypothesisStatus.ACTIVE
        ),
    )


class DeterministicReasoningProvider:
    """Evidence-driven provider for deterministic CI and offline development.

    It never reads ChaosLab controller state or scenario ground truth. Conclusions are
    derived only from evidence returned through the Phase 3 MCP registry.
    """

    name = "deterministic-evidence-v1"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        service = state.incident.service
        text = f"{state.incident.title} {state.incident.description}".lower()
        steps: list[PlanStep] = []

        def add(
            step_id: str,
            objective: str,
            tool: str,
            arguments: dict[str, Any],
            rationale: str,
        ) -> None:
            steps.append(
                PlanStep(
                    id=step_id,
                    objective=objective,
                    tool=tool,
                    arguments=arguments,
                    rationale=rationale,
                )
            )

        if service == "checkout":
            add(
                "latency",
                "Quantify the checkout latency regression.",
                "query_metrics",
                {"service": "checkout", "metric": "p95_latency"},
                "Confirm that the user-visible latency symptom is observable.",
            )
            if any(word in text for word in ("deploy", "release", "rollout", "change")):
                add(
                    "deployment",
                    "Inspect the currently observable checkout deployment.",
                    "inspect_deployment",
                    {"service": "checkout"},
                    "Establish deployment context without reading hidden fault state.",
                )
                add(
                    "git-diff",
                    "Inspect the most recent repository diff.",
                    "inspect_git_diff",
                    {"base": "HEAD~1", "head": "HEAD"},
                    "Look for recent code changes while treating the diff as context, not proof.",
                )
            add(
                "db-query-count",
                "Measure database query fan-out for checkout.",
                "query_metrics",
                {"service": "checkout", "metric": "db_query_count"},
                "N+1 behavior should produce an abnormal number of queries per request.",
            )
            add(
                "checkout-logs",
                "Inspect checkout request logs for query fan-out.",
                "search_logs",
                {"service": "checkout", "query": "/orders", "limit": 20},
                "Corroborate the metric with request-level evidence.",
            )
        elif service == "inventory":
            add(
                "db-connections",
                "Measure active inventory database connections.",
                "query_metrics",
                {"service": "inventory", "metric": "db_connections"},
                "Connection leaks should exhaust the simulated connection capacity.",
            )
            add(
                "inventory-errors",
                "Inspect recent inventory failures.",
                "search_logs",
                {"service": "inventory", "level": "ERROR", "limit": 20},
                "Correlate connection pressure with failed requests.",
            )
        elif service == "worker":
            add(
                "disk",
                "Measure worker disk utilization.",
                "query_metrics",
                {"service": "worker", "metric": "disk_usage"},
                "Separate disk exhaustion from memory pressure.",
            )
            add(
                "memory",
                "Measure worker memory utilization.",
                "query_metrics",
                {"service": "worker", "metric": "memory_usage"},
                "Look for monotonic or extreme memory pressure.",
            )
            add(
                "restarts",
                "Check whether the worker has restarted.",
                "query_metrics",
                {"service": "worker", "metric": "container_restarts"},
                "A memory failure can manifest as a restart after allocation pressure.",
            )
            add(
                "worker-errors",
                "Inspect worker errors.",
                "search_logs",
                {"service": "worker", "level": "ERROR", "limit": 20},
                "Corroborate resource metrics with request failures.",
            )
        elif service == "payment":
            add(
                "payment-warnings",
                "Inspect payment authentication/configuration warnings.",
                "search_logs",
                {"service": "payment", "level": "WARNING", "limit": 20},
                "Broken credentials or configuration should be visible at the payment boundary.",
            )
            add(
                "gateway-errors",
                "Inspect gateway failures caused by payment.",
                "search_logs",
                {"service": "gateway", "level": "ERROR", "limit": 20},
                "Confirm the upstream consequence independently.",
            )
        else:
            add(
                "error-rate",
                f"Measure {service} error rate.",
                "query_metrics",
                {"service": service, "metric": "error_rate"},
                "Establish the observable impact.",
            )
            add(
                "service-errors",
                f"Inspect {service} errors.",
                "search_logs",
                {"service": service, "level": "ERROR", "limit": 20},
                "Gather request-level evidence.",
            )

        return (
            InvestigationPlan(
                summary=(
                    f"Investigate {state.incident.title!r} using only the legal MCP "
                    "investigation surface and cross-check independent signals."
                ),
                steps=steps,
            ),
            ProviderUsage(),
        )

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        hypotheses: list[Hypothesis] = []

        query_count, query_eid = _metric_evidence(
            state.evidence, "checkout", "db_query_count"
        )
        n1_logs = _log_matches(
            state.evidence,
            service="checkout",
            field="db_queries",
            minimum=10.0,
        )
        n1_support = ([query_eid] if query_eid is not None else []) + n1_logs
        if query_count is not None and query_count > 10 and n1_logs:
            hypotheses.append(
                _hypothesis(
                    "n_plus_one_query",
                    (
                        "Checkout performs excessive per-request database queries "
                        "consistent with an N+1 query regression."
                    ),
                    0.97,
                    n1_support,
                )
            )
        elif query_count is not None and query_count > 10:
            hypotheses.append(
                _hypothesis(
                    "n_plus_one_query",
                    (
                        "Checkout database query fan-out is abnormally high and may "
                        "indicate an N+1 query regression."
                    ),
                    0.72,
                    n1_support,
                )
            )

        connections, connection_eid = _metric_evidence(
            state.evidence, "inventory", "db_connections"
        )
        connection_logs = _log_matches(
            state.evidence, service="inventory", status=503
        )
        connection_support = (
            ([connection_eid] if connection_eid is not None else []) + connection_logs
        )
        if connections is not None and connections >= 4 and connection_logs:
            hypotheses.append(
                _hypothesis(
                    "database_connection_leak",
                    (
                        "Inventory exhausts its database connection capacity, "
                        "consistent with a connection leak."
                    ),
                    0.96,
                    connection_support,
                )
            )

        disk, disk_eid = _metric_evidence(state.evidence, "worker", "disk_usage")
        disk_logs = _log_matches(state.evidence, service="worker", status=507)
        disk_support = ([disk_eid] if disk_eid is not None else []) + disk_logs
        if disk is not None and disk >= 0.95 and disk_logs:
            hypotheses.append(
                _hypothesis(
                    "disk_exhaustion",
                    (
                        "Worker disk capacity is exhausted and requests fail with "
                        "insufficient-storage errors."
                    ),
                    0.99,
                    disk_support,
                )
            )

        restarts, restart_eid = _metric_evidence(
            state.evidence, "worker", "container_restarts"
        )
        memory, memory_eid = _metric_evidence(
            state.evidence, "worker", "memory_usage"
        )
        memory_logs = _log_matches(state.evidence, service="worker", status=503)
        memory_support = (
            ([restart_eid] if restart_eid is not None else [])
            + ([memory_eid] if memory_eid is not None else [])
            + memory_logs
        )
        if (
            restarts is not None
            and restarts >= 1
            and memory_logs
            and (disk is None or disk < 0.95)
        ):
            hypotheses.append(
                _hypothesis(
                    "memory_leak",
                    (
                        "Worker resource growth culminates in a restart and 503 failure, "
                        "consistent with a memory leak."
                    ),
                    0.95,
                    memory_support,
                )
            )
        elif memory is not None and memory > 0 and memory_eid is not None:
            hypotheses.append(
                _hypothesis(
                    "memory_pressure",
                    "Worker memory usage is elevated and warrants additional corroboration.",
                    0.55,
                    [memory_eid],
                )
            )

        payment_401 = _log_matches(state.evidence, service="payment", status=401)
        gateway_502 = _log_matches(state.evidence, service="gateway", status=502)
        if payment_401 and gateway_502:
            hypotheses.append(
                _hypothesis(
                    "broken_payment_configuration",
                    (
                        "Payment rejects requests with authentication/configuration "
                        "failures and the gateway surfaces the dependency failure."
                    ),
                    0.97,
                    payment_401 + gateway_502,
                )
            )

        return hypotheses, ProviderUsage()

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        top = max((item.confidence for item in state.hypotheses), default=0.0)
        if top < 0.9:
            plan = state.plan
            all_done = plan is not None and all(
                step.completed for step in plan.steps if step.required
            )
            return all_done, ProviderUsage()

        text = f"{state.incident.title} {state.incident.description}".lower()
        if state.incident.service == "checkout" and any(
            word in text for word in ("deploy", "release", "rollout", "change")
        ):
            required = {
                "latency",
                "deployment",
                "git-diff",
                "db-query-count",
                "checkout-logs",
            }
            completed = {
                step.id for step in (state.plan.steps if state.plan else []) if step.completed
            }
            return required.issubset(completed), ProviderUsage()
        return True, ProviderUsage()

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        if not state.hypotheses:
            evidence_ids = [item.id for item in state.evidence]
            return (
                "inconclusive",
                Diagnosis(
                    primary_root_cause="Insufficient evidence to identify a primary root cause.",
                    confidence=0.0,
                    evidence_ids=evidence_ids,
                    recommended_actions=[],
                ),
                ProviderUsage(),
            )

        top = max(state.hypotheses, key=lambda item: item.confidence)
        evidence_ids = list(
            dict.fromkeys(top.supporting_evidence + top.contradicting_evidence)
        )
        return (
            top.root_cause_code,
            Diagnosis(
                primary_root_cause=top.description,
                confidence=top.confidence,
                evidence_ids=evidence_ids,
                recommended_actions=[],
            ),
            ProviderUsage(),
        )

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        if state.final_diagnosis is None or not state.final_diagnosis.evidence_ids:
            return None, ProviderUsage()

        code = (
            max(state.hypotheses, key=lambda item: item.confidence).root_cause_code
            if state.hypotheses
            else "inconclusive"
        )
        actions = {
            "n_plus_one_query": (
                (
                    "Review the recent checkout data-access change and replace repeated "
                    "per-item queries with an eager-loaded or batched query, then rerun "
                    "latency and query-count verification."
                ),
                RiskLevel.R2,
            ),
            "database_connection_leak": (
                (
                    "Fix inventory connection lifecycle handling and verify connections "
                    "are released on success and failure paths."
                ),
                RiskLevel.R2,
            ),
            "disk_exhaustion": (
                (
                    "Free or rotate worker output safely, then add bounded retention and "
                    "disk-pressure protection."
                ),
                RiskLevel.R2,
            ),
            "memory_leak": (
                (
                    "Identify the retained worker allocation path, bound or release "
                    "retained objects, and verify memory remains stable under repeated work."
                ),
                RiskLevel.R2,
            ),
            "broken_payment_configuration": (
                (
                    "Correct the payment authentication/configuration value through the "
                    "approved deployment process and verify both payment and gateway health."
                ),
                RiskLevel.R2,
            ),
        }
        action = actions.get(code)
        if action is None:
            return None, ProviderUsage()
        description, risk = action
        return (
            ProposedAction(
                description=description,
                risk_level=risk,
                rationale=(
                    "Recommendation is derived from the evidence-grounded Phase 4 diagnosis; "
                    "Phase 4 does not execute remediation."
                ),
                evidence_ids=state.final_diagnosis.evidence_ids,
            ),
            ProviderUsage(),
        )


class OllamaReasoningProvider(DeterministicReasoningProvider):
    """Optional local/open-model planner using Ollama structured output.

    Evidence interpretation remains constrained by deterministic evidence-grounding
    rules in Phase 4. The model is used to order legal investigation steps, and its
    output must validate against the typed InvestigationPlan schema.
    """

    name = "ollama-local-v1"

    def __init__(self, *, base_url: str, model: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        baseline, _ = await super().plan(state)
        legal_steps = [step.model_dump(mode="json") for step in baseline.steps]
        prompt = {
            "incident": state.incident.model_dump(mode="json"),
            "legal_steps": legal_steps,
            "instruction": (
                "Return an InvestigationPlan using only the supplied legal steps. "
                "Do not add tools, hidden simulator state, or unsupported facts. "
                "Preserve all required steps; you may only reorder them and rewrite "
                "the summary/rationales."
            ),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "format": InvestigationPlan.model_json_schema(),
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are the planning component of a constrained "
                                    "incident investigator. Evidence is distinct from "
                                    "interpretation and only supplied MCP tools are legal."
                                ),
                            },
                            {"role": "user", "content": json.dumps(prompt)},
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ReasoningProviderError("local Ollama provider is unavailable") from exc

        try:
            content = payload["message"]["content"]
            plan = InvestigationPlan.model_validate_json(content)
        except (KeyError, TypeError, ValueError) as exc:
            raise ReasoningProviderError(
                "local Ollama provider returned invalid structured output"
            ) from exc

        baseline_by_id = {step.id: step for step in baseline.steps}
        returned_ids = [step.id for step in plan.steps]
        if set(returned_ids) != set(baseline_by_id) or len(returned_ids) != len(
            baseline_by_id
        ):
            raise ReasoningProviderError(
                "local Ollama provider changed the legal investigation step set"
            )
        for step in plan.steps:
            legal = baseline_by_id[step.id]
            if step.tool != legal.tool or step.arguments != legal.arguments:
                raise ReasoningProviderError(
                    "local Ollama provider changed a legal tool invocation"
                )

        input_tokens = int(payload.get("prompt_eval_count", 0) or 0)
        output_tokens = int(payload.get("eval_count", 0) or 0)
        return plan, ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=0.0,
        )
