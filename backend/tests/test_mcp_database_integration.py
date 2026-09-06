import os

import psycopg
import pytest

from app.config import Settings
from app.mcp.models import ExecuteSqlArgs, PermissionSet
from app.mcp.tools import InvestigationTools


pytestmark = pytest.mark.integration


def settings() -> Settings:
    return Settings(
        mcp_database_url=os.getenv(
            "OPSSENTINEL_MCP_DATABASE_URL",
            "postgresql://opssentinel_reader:opssentinel_readonly@localhost:5432/opssentinel_test",
        )
    )


def permissions() -> PermissionSet:
    return PermissionSet(principal="integration", allowed_services=set(), allowed_tools=set())


@pytest.mark.asyncio
async def test_restricted_sql_user_can_read_but_not_mutate() -> None:
    target = settings()
    tools = InvestigationTools(target, permissions())
    result = await tools.execute_sql(
        ExecuteSqlArgs(query="SELECT current_user, COUNT(*) FROM incidents")
    )
    assert result.payload["rows"][0][0] == "opssentinel_reader"

    with psycopg.connect(target.mcp_database_url) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.Error):
            cur.execute("UPDATE incidents SET title = title")
