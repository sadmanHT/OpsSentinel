"""Create the restricted Phase 3 investigation database role.

Revision ID: 0002_mcp_readonly_role
Revises: 0001_initial
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002_mcp_readonly_role"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opssentinel_reader') THEN
                CREATE ROLE opssentinel_reader
                    LOGIN
                    PASSWORD 'opssentinel_readonly'
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE
                    NOINHERIT
                    NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute("ALTER ROLE opssentinel_reader SET default_transaction_read_only = on")
    op.execute("GRANT USAGE ON SCHEMA public TO opssentinel_reader")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO opssentinel_reader")
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE opssentinel IN SCHEMA public
        GRANT SELECT ON TABLES TO opssentinel_reader
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE opssentinel IN SCHEMA public
        REVOKE SELECT ON TABLES FROM opssentinel_reader
        """
    )
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM opssentinel_reader")
    op.execute("REVOKE USAGE ON SCHEMA public FROM opssentinel_reader")
    op.execute("DROP ROLE IF EXISTS opssentinel_reader")
