"""Add Phase 9 model execution observability.

Revision ID: 0006_phase9_model_executions
Revises: 0005_experiment_trials
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase9_model_executions"
down_revision: str | None = "0005_experiment_trials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(160), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_type", sa.String(160)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_model_executions_run_id",
        "model_executions",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_executions_run_id", table_name="model_executions")
    op.drop_table("model_executions")
