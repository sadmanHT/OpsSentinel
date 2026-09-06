from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import Engine, MetaData, Table, delete, insert, select

from researchlab.models import ResearchConfiguration, TrialIdentity, TrialRecord


def _json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


class SqlTrialStore:
    """Durable Phase 8 trial lifecycle journal backed by canonical PostgreSQL."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata = MetaData()
        self.trials = Table("experiment_trials", metadata, autoload_with=engine)

    def load(self, trial_id: UUID) -> TrialRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.trials).where(self.trials.c.id == str(trial_id))
            ).mappings().first()
        if row is None:
            return None

        configuration = ResearchConfiguration.model_validate(
            _json_object(row["configuration"], "experiment trial configuration")
        )
        explicit_configuration = {
            "architecture": row["architecture"],
            "provider": row["provider"],
            "model": row["model"],
            "prompt_version": row["prompt_version"],
        }
        for key, expected in explicit_configuration.items():
            actual = getattr(configuration, key)
            actual_value = actual.value if hasattr(actual, "value") else actual
            if actual_value != expected:
                raise ValueError(
                    f"experiment trial configuration mismatch for {key}: "
                    f"{actual_value!r} != {expected!r}"
                )

        identity = TrialIdentity.model_validate(
            {
                "trial_id": row["id"],
                "plan_id": row["plan_id"],
                "experiment": row["experiment"],
                "cell_id": row["cell_id"],
                "scenario_id": row["scenario_id"],
                "scenario_version": row["scenario_version"],
                "dataset_version": row["dataset_version"],
                "split": row["split"],
                "difficulty": row["difficulty"],
                "repeat_index": row["repeat_index"],
                "seed": row["seed"],
                "configuration": configuration,
                "configuration_hash": row["configuration_hash"],
            }
        )
        return TrialRecord.model_validate(
            {
                "identity": identity,
                "status": row["status"],
                "evaluation_run_id": row["evaluation_run_id"],
                "agent_run_id": row["agent_run_id"],
                "raw_trajectory": _json_object(
                    row["raw_trajectory"], "experiment trial raw_trajectory"
                ),
                "scores": _json_object(row["scores"], "experiment trial scores"),
                "error": row["error"],
                "updated_at": row["updated_at"],
            }
        )

    def save(self, record: TrialRecord) -> None:
        identity = record.identity
        configuration = identity.configuration
        values = {
            "id": str(identity.trial_id),
            "plan_id": identity.plan_id,
            "experiment": identity.experiment.value,
            "cell_id": identity.cell_id,
            "scenario_id": identity.scenario_id,
            "scenario_version": identity.scenario_version,
            "dataset_version": identity.dataset_version,
            "split": identity.split.value,
            "difficulty": identity.difficulty.value,
            "repeat_index": identity.repeat_index,
            "seed": identity.seed,
            "architecture": configuration.architecture.value,
            "provider": configuration.provider,
            "model": configuration.model,
            "prompt_version": configuration.prompt_version,
            "configuration": configuration.model_dump(mode="json"),
            "configuration_hash": identity.configuration_hash,
            "status": record.status.value,
            "evaluation_run_id": (
                str(record.evaluation_run_id) if record.evaluation_run_id is not None else None
            ),
            "agent_run_id": str(record.agent_run_id) if record.agent_run_id is not None else None,
            "raw_trajectory": record.raw_trajectory,
            "scores": record.scores,
            "error": record.error,
            "updated_at": record.updated_at,
        }
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.trials).where(self.trials.c.id == str(identity.trial_id))
            )
            connection.execute(insert(self.trials).values(**values))

    def list_plan(self, plan_id: str) -> list[TrialRecord]:
        with self.engine.connect() as connection:
            trial_ids = connection.execute(
                select(self.trials.c.id)
                .where(self.trials.c.plan_id == plan_id)
                .order_by(self.trials.c.id)
            ).scalars()
            ids = [UUID(str(value)) for value in trial_ids]
        return [record for trial_id in ids if (record := self.load(trial_id)) is not None]
