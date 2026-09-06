from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field, model_validator
from sqlalchemy import Engine, MetaData, Table, delete, insert, select

from evaluationlab.counterfactual import CounterfactualMetrics
from evaluationlab.models import EvaluationResult, FailureCategory, StrictModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class EvaluationRunMetadata(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    dataset_version: str = Field(min_length=1, max_length=80)
    architecture_version: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    seed: int = Field(ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_timezone(self) -> EvaluationRunMetadata:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("evaluation run created_at must be timezone-aware")
        return self


class ExperimentConfiguration(StrictModel):
    prompt_version: str = Field(min_length=1, max_length=80)
    scenario_version: str = Field(min_length=1, max_length=80)
    evaluation_version: str = Field(min_length=1, max_length=80)
    retrieval_settings: dict[str, Any] = Field(default_factory=dict)
    tool_budget: int = Field(ge=0)
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_timezone(self) -> ExperimentConfiguration:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("experiment recorded_at must be timezone-aware")
        return self


class PersistedEvaluation(StrictModel):
    evaluation_run_id: UUID
    agent_run_id: UUID | None = None
    result: EvaluationResult
    trace: dict[str, Any] = Field(default_factory=dict)
    failure_categories: list[FailureCategory] = Field(default_factory=list)


def _json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return cast(list[str], value)


def _metric_values(result: EvaluationResult) -> dict[str, float]:
    values = {
        "root_cause.primary_accuracy": result.root_cause.primary_accuracy,
        "root_cause.secondary_recall": result.root_cause.secondary_recall,
        "root_cause.multi_root_cause_precision": result.root_cause.multi_root_cause_precision,
        "root_cause.multi_root_cause_recall": result.root_cause.multi_root_cause_recall,
        "root_cause.exact_match": float(result.root_cause.exact_match),
        "evidence.precision": result.evidence.precision,
        "evidence.recall": result.evidence.recall,
        "evidence.critical_recall": result.evidence.critical_recall,
        "evidence.distractor_selection_rate": result.evidence.distractor_selection_rate,
        "efficiency.useful_evidence_per_tool_call": result.efficiency.useful_evidence_per_tool_call,
        "efficiency.duplicate_tool_calls": float(result.efficiency.duplicate_tool_calls),
        "efficiency.irrelevant_tool_calls": float(result.efficiency.irrelevant_tool_calls),
        "efficiency.failed_tool_calls": float(result.efficiency.failed_tool_calls),
        "efficiency.misleading_tool_calls": float(result.efficiency.misleading_tool_calls),
        "efficiency.total_tool_calls": float(result.efficiency.total_tool_calls),
        "confidence": result.confidence,
        "correctness": result.correctness,
        "brier_component": result.brier_component,
        "safety.unsafe_action_attempts": float(result.safety.unsafe_action_attempts),
        "safety.blocked_destructive_requests": float(result.safety.blocked_destructive_requests),
        "safety.unnecessary_approval_requests": float(result.safety.unnecessary_approval_requests),
        "safety.incorrectly_classified_risk": float(result.safety.incorrectly_classified_risk),
    }
    if result.efficiency.steps_to_correct_hypothesis is not None:
        values["efficiency.steps_to_correct_hypothesis"] = float(
            result.efficiency.steps_to_correct_hypothesis
        )
    return values


def _counterfactual_metric_values(metrics: CounterfactualMetrics) -> dict[str, float]:
    values = {"counterfactual.consistency": metrics.consistency}
    if metrics.causal_sensitivity is not None:
        values["counterfactual.causal_sensitivity"] = metrics.causal_sensitivity
    if metrics.causal_invariance is not None:
        values["counterfactual.causal_invariance"] = metrics.causal_invariance
    return values


def _counterfactual_scope(family: str) -> str:
    return f"counterfactual:{family}"


class SqlEvaluationStore:
    """Persist deterministic evaluation outputs into the canonical OpsSentinel schema."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata = MetaData()
        self.runs = Table("evaluation_runs", metadata, autoload_with=engine)
        self.scores = Table("evaluation_scores", metadata, autoload_with=engine)
        self.experiments = Table("experiment_metadata", metadata, autoload_with=engine)

    def create_run(
        self,
        run: EvaluationRunMetadata,
        experiment: ExperimentConfiguration | None = None,
    ) -> None:
        run_id = str(run.id)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(self.runs.c.id).where(self.runs.c.id == run_id)
            ).first()
            if existing is not None:
                raise ValueError(f"evaluation run {run.id} already exists")
            connection.execute(
                insert(self.runs).values(
                    id=run_id,
                    dataset_version=run.dataset_version,
                    architecture_version=run.architecture_version,
                    model=run.model,
                    seed=run.seed,
                    configuration=run.configuration,
                    created_at=run.created_at,
                )
            )
            if experiment is not None:
                experiment_id = uuid5(
                    NAMESPACE_URL,
                    f"opssentinel:experiment-metadata:{run_id}",
                )
                connection.execute(
                    insert(self.experiments).values(
                        id=str(experiment_id),
                        evaluation_run_id=run_id,
                        prompt_version=experiment.prompt_version,
                        scenario_version=experiment.scenario_version,
                        evaluation_version=experiment.evaluation_version,
                        retrieval_settings=experiment.retrieval_settings,
                        tool_budget=experiment.tool_budget,
                        recorded_at=experiment.recorded_at,
                    )
                )

    def save_result(
        self,
        evaluation_run_id: UUID,
        result: EvaluationResult,
        *,
        agent_run_id: UUID | None = None,
        trace: dict[str, Any] | None = None,
    ) -> None:
        run_id = str(evaluation_run_id)
        trace_payload = trace or {}
        failure_categories = [
            classification.category.value for classification in result.failure_classifications
        ]
        with self.engine.begin() as connection:
            run_exists = connection.execute(
                select(self.runs.c.id).where(self.runs.c.id == run_id)
            ).first()
            if run_exists is None:
                raise ValueError(f"evaluation run {evaluation_run_id} does not exist")
            connection.execute(
                delete(self.scores).where(
                    self.scores.c.evaluation_run_id == run_id,
                    self.scores.c.scenario_id == result.scenario_id,
                )
            )
            for metric_name, score in _metric_values(result).items():
                score_id = uuid5(
                    NAMESPACE_URL,
                    "opssentinel:evaluation-score:"
                    f"{run_id}:{result.scenario_id}:{metric_name}",
                )
                details: dict[str, Any] = {}
                if metric_name == "correctness":
                    details["evaluation_result"] = result.model_dump(mode="json")
                connection.execute(
                    insert(self.scores).values(
                        id=str(score_id),
                        evaluation_run_id=run_id,
                        agent_run_id=str(agent_run_id) if agent_run_id is not None else None,
                        scenario_id=result.scenario_id,
                        metric_name=metric_name,
                        score=score,
                        details=details,
                        trace=trace_payload,
                        failure_categories=failure_categories,
                    )
                )

    def save_counterfactual_metrics(
        self,
        evaluation_run_id: UUID,
        metrics: CounterfactualMetrics,
        *,
        trace: dict[str, Any] | None = None,
    ) -> None:
        run_id = str(evaluation_run_id)
        scenario_id = _counterfactual_scope(metrics.family)
        trace_payload = trace or {}
        with self.engine.begin() as connection:
            run_exists = connection.execute(
                select(self.runs.c.id).where(self.runs.c.id == run_id)
            ).first()
            if run_exists is None:
                raise ValueError(f"evaluation run {evaluation_run_id} does not exist")
            connection.execute(
                delete(self.scores).where(
                    self.scores.c.evaluation_run_id == run_id,
                    self.scores.c.scenario_id == scenario_id,
                )
            )
            for metric_name, score in _counterfactual_metric_values(metrics).items():
                score_id = uuid5(
                    NAMESPACE_URL,
                    "opssentinel:evaluation-score:"
                    f"{run_id}:{scenario_id}:{metric_name}",
                )
                details: dict[str, Any] = {}
                if metric_name == "counterfactual.consistency":
                    details["counterfactual_metrics"] = metrics.model_dump(mode="json")
                connection.execute(
                    insert(self.scores).values(
                        id=str(score_id),
                        evaluation_run_id=run_id,
                        agent_run_id=None,
                        scenario_id=scenario_id,
                        metric_name=metric_name,
                        score=score,
                        details=details,
                        trace=trace_payload,
                        failure_categories=[],
                    )
                )

    def load_run(self, evaluation_run_id: UUID) -> EvaluationRunMetadata | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.runs).where(self.runs.c.id == str(evaluation_run_id))
            ).mappings().first()
        if row is None:
            return None
        return EvaluationRunMetadata.model_validate(dict(row))

    def load_experiment(self, evaluation_run_id: UUID) -> ExperimentConfiguration | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.experiments).where(
                    self.experiments.c.evaluation_run_id == str(evaluation_run_id)
                )
            ).mappings().first()
        if row is None:
            return None
        payload = dict(row)
        payload.pop("id", None)
        payload.pop("evaluation_run_id", None)
        return ExperimentConfiguration.model_validate(payload)

    def load_result(
        self,
        evaluation_run_id: UUID,
        scenario_id: str,
    ) -> PersistedEvaluation | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.scores).where(
                    self.scores.c.evaluation_run_id == str(evaluation_run_id),
                    self.scores.c.scenario_id == scenario_id,
                    self.scores.c.metric_name == "correctness",
                )
            ).mappings().first()
        if row is None:
            return None

        details = _json_object(row["details"], "evaluation score details")
        result_payload = details.get("evaluation_result")
        result = EvaluationResult.model_validate(result_payload)
        trace = _json_object(row["trace"], "evaluation trace")
        categories = [
            FailureCategory(item)
            for item in _string_list(
                row["failure_categories"],
                "evaluation failure_categories",
            )
        ]
        agent_run_value = row["agent_run_id"]
        if agent_run_value is not None and not isinstance(agent_run_value, str):
            raise ValueError("evaluation agent_run_id must be a string or null")
        return PersistedEvaluation(
            evaluation_run_id=evaluation_run_id,
            agent_run_id=UUID(agent_run_value) if agent_run_value is not None else None,
            result=result,
            trace=trace,
            failure_categories=categories,
        )

    def load_counterfactual_metrics(
        self,
        evaluation_run_id: UUID,
        family: str,
    ) -> CounterfactualMetrics | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.scores).where(
                    self.scores.c.evaluation_run_id == str(evaluation_run_id),
                    self.scores.c.scenario_id == _counterfactual_scope(family),
                    self.scores.c.metric_name == "counterfactual.consistency",
                )
            ).mappings().first()
        if row is None:
            return None
        details = _json_object(row["details"], "counterfactual score details")
        return CounterfactualMetrics.model_validate(details.get("counterfactual_metrics"))

    def metric_names(self, evaluation_run_id: UUID, scenario_id: str) -> list[str]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(self.scores.c.metric_name).where(
                    self.scores.c.evaluation_run_id == str(evaluation_run_id),
                    self.scores.c.scenario_id == scenario_id,
                )
            ).scalars()
            return sorted(str(value) for value in rows)

    def counterfactual_metric_names(self, evaluation_run_id: UUID, family: str) -> list[str]:
        return self.metric_names(evaluation_run_id, _counterfactual_scope(family))
