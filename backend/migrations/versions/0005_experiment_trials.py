"""Add Phase 8 experiment trial lifecycle journal.

Revision ID: 0005_experiment_trials
Revises: 0004_evaluation_traceability
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_experiment_trials"
down_revision: str | None = "0004_evaluation_traceability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_trials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(100), nullable=False),
        sa.Column("experiment", sa.String(80), nullable=False),
        sa.Column("cell_id", sa.String(80), nullable=False),
        sa.Column("scenario_id", sa.String(120), nullable=False),
        sa.Column("scenario_version", sa.String(40), nullable=False),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("split", sa.String(32), nullable=False),
        sa.Column("difficulty", sa.String(32), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("architecture", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "evaluation_run_id",
            sa.String(36),
            sa.ForeignKey("evaluation_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "agent_run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("raw_trajectory", sa.JSON(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_experiment_trials_plan_status",
        "experiment_trials",
        ["plan_id", "status"],
    )
    op.create_index(
        "ix_experiment_trials_scenario",
        "experiment_trials",
        ["scenario_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_trials_scenario", table_name="experiment_trials")
    op.drop_index("ix_experiment_trials_plan_status", table_name="experiment_trials")
    op.drop_table("experiment_trials")
