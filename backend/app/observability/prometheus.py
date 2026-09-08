from __future__ import annotations

from collections import Counter

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.observability.persistence import ModelExecutionRecord
from app.observability.store import SqlObservabilityStore
from app.persistence.models import AgentRunRecord, EvidenceRecord, ToolCallRecord
from app.persistence.session import create_session_factory


class SqlPrometheusExporter:
    """Render low-cardinality Prometheus metrics from durable OpsSentinel state."""

    def __init__(self, engine: Engine) -> None:
        self.session_factory: sessionmaker[Session] = create_session_factory(engine)
        self.observability_store = SqlObservabilityStore(engine)

    def render(self) -> bytes:
        registry = CollectorRegistry(auto_describe=True)

        run_count = Gauge(
            "opssentinel_agent_runs",
            "Durable agent run count by status.",
            ["status"],
            registry=registry,
        )
        run_tokens = Gauge(
            "opssentinel_agent_token_usage",
            "Durable aggregate token usage across agent runs.",
            registry=registry,
        )
        run_cost = Gauge(
            "opssentinel_agent_estimated_cost",
            "Durable aggregate estimated cost across agent runs.",
            registry=registry,
        )
        tool_calls = Gauge(
            "opssentinel_tool_calls",
            "Durable MCP tool-call count by stable tool name and status.",
            ["tool", "status"],
            registry=registry,
        )
        evidence_items = Gauge(
            "opssentinel_evidence_items",
            "Durable evidence item count by evidence type.",
            ["type"],
            registry=registry,
        )
        model_executions = Gauge(
            "opssentinel_model_executions",
            "Durable model execution count by operation and status.",
            ["operation", "status"],
            registry=registry,
        )
        model_tokens = Gauge(
            "opssentinel_model_token_usage",
            "Durable model-execution token usage by direction.",
            ["direction"],
            registry=registry,
        )
        model_cost = Gauge(
            "opssentinel_model_estimated_cost",
            "Durable aggregate model-provider estimated cost.",
            registry=registry,
        )
        latency_observations = Gauge(
            "opssentinel_run_latency_observations",
            "Number of durable runs contributing to each latency stage.",
            ["stage"],
            registry=registry,
        )
        latency_ms = Gauge(
            "opssentinel_run_latency_milliseconds",
            "Durable run latency percentile by stage.",
            ["stage", "quantile"],
            registry=registry,
        )

        with self.session_factory() as session:
            runs = list(session.scalars(select(AgentRunRecord)).all())
            calls = list(session.scalars(select(ToolCallRecord)).all())
            evidence = list(session.scalars(select(EvidenceRecord)).all())
            executions = list(session.scalars(select(ModelExecutionRecord)).all())

        for status, count in Counter(run.status for run in runs).items():
            run_count.labels(status=status).set(count)
        run_tokens.set(sum(run.token_usage for run in runs))
        run_cost.set(sum(run.estimated_cost for run in runs))

        for (tool, status), count in Counter(
            (call.tool_name, call.status) for call in calls
        ).items():
            tool_calls.labels(tool=tool, status=status).set(count)

        for evidence_type, count in Counter(item.evidence_type for item in evidence).items():
            evidence_items.labels(type=evidence_type).set(count)

        for (operation, status), count in Counter(
            (execution.operation, execution.status) for execution in executions
        ).items():
            model_executions.labels(operation=operation, status=status).set(count)
        model_tokens.labels(direction="input").set(
            sum(execution.input_tokens for execution in executions)
        )
        model_tokens.labels(direction="output").set(
            sum(execution.output_tokens for execution in executions)
        )
        model_cost.set(sum(execution.estimated_cost for execution in executions))

        latency = self.observability_store.summarize_latency()
        stages = {
            "first_investigation_step": latency.time_to_first_investigation_step,
            "diagnosis": latency.time_to_diagnosis,
            "verified_resolution": latency.time_to_verified_resolution,
        }
        for stage, distribution in stages.items():
            latency_observations.labels(stage=stage).set(distribution.count)
            if distribution.p50_ms is not None:
                latency_ms.labels(stage=stage, quantile="0.50").set(distribution.p50_ms)
            if distribution.p95_ms is not None:
                latency_ms.labels(stage=stage, quantile="0.95").set(distribution.p95_ms)

        return generate_latest(registry)
