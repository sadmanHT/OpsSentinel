"""Add persistent Phase 4 agent checkpoints.

Revision ID: 0003_agent_checkpoints
Revises: 0002_mcp_readonly_role
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_agent_checkpoints"
down_revision: str | None = "0002_mcp_readonly_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_checkpoints",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("next_node", sa.String(80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_checkpoints")
