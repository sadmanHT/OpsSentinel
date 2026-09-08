from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from statistics import fmean
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.domain import StrictModel
from app.persistence.models import (
    EvaluationRunRecord,
    EvaluationScoreRecord,
    ExperimentMetadataRecord,
)
from app.persistence.session import create_session_factory


class ExperimentMetrics(StrictModel):
    correctness_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    primary_root_cause_accuracy_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_precision_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_recall_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    total_tool_calls_mean: float | None = Field(default=None, ge=0.0)
    unsafe_action_attempts_total: float | None = Field(default=None, ge=0.0)


class ExperimentRunSummary(StrictModel):
    evaluation_run_id: UUID
    dataset_version: str
    architecture_version: str
    model: str
    seed: int = Field(ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    prompt_version: str | None = None
    scenario_version: str | None = None
    evaluation_version: str | None = None
    retrieval_settings: dict[str, Any] = Field(default_factory=dict)
    tool_budget: int | None = Field(default=None, ge=0)
    recorded_at: datetime | None = None
    scenario_count: int = Field(ge=0)
    linked_agent_run_count: int = Field(ge=0)
    metrics: ExperimentMetrics
    failure_categories: dict[str, int] = Field(default_factory=dict)


class ExperimentDashboard(StrictModel):
    run_count: int = Field(ge=0)
    runs: list[ExperimentRunSummary]


def _mean_score(scores: Iterable[EvaluationScoreRecord], metric_name: str) -> float | None:
    values = [score.score for score in scores if score.metric_name == metric_name]
    return fmean(values) if values else None


def _sum_score(scores: Iterable[EvaluationScoreRecord], metric_name: str) -> float | None:
    values = [score.score for score in scores if score.metric_name == metric_name]
    return sum(values) if values else None


class SqlExperimentDashboardStore:
    """Read persisted evaluation and experiment records for the Phase 9 UI."""

    def __init__(self, engine: Engine) -> None:
        self.session_factory: sessionmaker[Session] = create_session_factory(engine)

    def list_runs(self, *, limit: int = 20) -> ExperimentDashboard:
        if limit < 1 or limit > 100:
            raise ValueError("experiment dashboard limit must be between 1 and 100")

        with self.session_factory() as session:
            runs = list(
                session.scalars(
                    select(EvaluationRunRecord)
                    .order_by(EvaluationRunRecord.created_at.desc())
                    .limit(limit)
                ).all()
            )
            summaries = [self._summarize_run(session, run) for run in runs]

        return ExperimentDashboard(run_count=len(summaries), runs=summaries)

    def _summarize_run(
        self,
        session: Session,
        run: EvaluationRunRecord,
    ) -> ExperimentRunSummary:
        experiment = session.scalar(
            select(ExperimentMetadataRecord)
            .where(ExperimentMetadataRecord.evaluation_run_id == run.id)
            .order_by(ExperimentMetadataRecord.recorded_at.desc())
            .limit(1)
        )
        scores = list(
            session.scalars(
                select(EvaluationScoreRecord).where(
                    EvaluationScoreRecord.evaluation_run_id == run.id
                )
            ).all()
        )
        correctness_rows = [score for score in scores if score.metric_name == "correctness"]
        failure_counts: Counter[str] = Counter()
        for score in correctness_rows:
            failure_counts.update(score.failure_categories)

        linked_agent_runs = {
            score.agent_run_id for score in correctness_rows if score.agent_run_id is not None
        }

        return ExperimentRunSummary(
            evaluation_run_id=UUID(run.id),
            dataset_version=run.dataset_version,
            architecture_version=run.architecture_version,
            model=run.model,
            seed=run.seed,
            configuration=run.configuration,
            created_at=run.created_at,
            prompt_version=experiment.prompt_version if experiment is not None else None,
            scenario_version=experiment.scenario_version if experiment is not None else None,
            evaluation_version=experiment.evaluation_version if experiment is not None else None,
            retrieval_settings=experiment.retrieval_settings if experiment is not None else {},
            tool_budget=experiment.tool_budget if experiment is not None else None,
            recorded_at=experiment.recorded_at if experiment is not None else None,
            scenario_count=len(correctness_rows),
            linked_agent_run_count=len(linked_agent_runs),
            metrics=ExperimentMetrics(
                correctness_mean=_mean_score(scores, "correctness"),
                confidence_mean=_mean_score(scores, "confidence"),
                primary_root_cause_accuracy_mean=_mean_score(
                    scores,
                    "root_cause.primary_accuracy",
                ),
                evidence_precision_mean=_mean_score(scores, "evidence.precision"),
                evidence_recall_mean=_mean_score(scores, "evidence.recall"),
                total_tool_calls_mean=_mean_score(scores, "efficiency.total_tool_calls"),
                unsafe_action_attempts_total=_sum_score(
                    scores,
                    "safety.unsafe_action_attempts",
                ),
            ),
            failure_categories=dict(sorted(failure_counts.items())),
        )
