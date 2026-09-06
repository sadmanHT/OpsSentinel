"""Add Phase 7 evaluation traceability fields.

Revision ID: 0004_evaluation_traceability
Revises: 0003_agent_checkpoints
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_evaluation_traceability"
down_revision: str | None = "0003_agent_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_scores",
        sa.Column(
            "agent_run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "evaluation_scores",
        sa.Column("trace", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "evaluation_scores",
        sa.Column(
            "failure_categories",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.create_index(
        "ix_evaluation_scores_run_scenario",
        "evaluation_scores",
        ["evaluation_run_id", "scenario_id"],
    )
    op.create_index(
        "ix_evaluation_scores_agent_run_id",
        "evaluation_scores",
        ["agent_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_scores_agent_run_id", table_name="evaluation_scores")
    op.drop_index("ix_evaluation_scores_run_scenario", table_name="evaluation_scores")
    op.drop_column("evaluation_scores", "failure_categories")
    op.drop_column("evaluation_scores", "trace")
    op.drop_column("evaluation_scores", "agent_run_id")
