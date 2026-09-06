from pathlib import Path

import pytest

from app.mcp.errors import InvalidToolArguments, UnsafeOperation
from app.mcp.safety import safe_relative_path, validate_git_ref, validate_readonly_sql


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "SHOW transaction_read_only",
        "EXPLAIN SELECT * FROM incidents",
        "EXPLAIN ANALYZE SELECT * FROM incidents",
    ],
)
def test_readonly_sql_allows_phase3_statements(query: str) -> None:
    assert validate_readonly_sql(query)


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO incidents(id) VALUES ('x')",
        "UPDATE incidents SET title = 'x'",
        "DELETE FROM incidents",
        "DROP TABLE incidents",
        "SELECT 1; SELECT 2",
        "SELECT * INTO temp_table FROM incidents",
        "SELECT * FROM incidents FOR UPDATE",
        "EXPLAIN DELETE FROM incidents",
        "SELECT pg_read_file('/etc/passwd')",
    ],
)
def test_mutation_and_dangerous_sql_are_blocked(query: str) -> None:
    with pytest.raises(UnsafeOperation):
        validate_readonly_sql(query)


def test_path_traversal_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(UnsafeOperation):
        safe_relative_path(tmp_path, "../outside")


def test_git_ref_cannot_be_an_option() -> None:
    with pytest.raises(InvalidToolArguments):
        validate_git_ref("--help")
