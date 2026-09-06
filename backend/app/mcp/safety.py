import re
from pathlib import Path

from app.mcp.errors import InvalidToolArguments, UnsafeOperation

_GIT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^-]{0,79}$")
_SQL_COMMENT = re.compile(r"(--[^\n]*|/\*.*?\*/)", flags=re.DOTALL)
_FORBIDDEN_SQL = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|"
    r"COPY|CALL|DO|SET|RESET|VACUUM|LOCK|REFRESH|REINDEX|CLUSTER"
    r")\b",
    flags=re.IGNORECASE,
)
_DANGEROUS_SQL = re.compile(
    r"\b("
    r"pg_write_file|pg_read_file|pg_read_binary_file|pg_ls_dir|"
    r"lo_import|lo_export|dblink|nextval|setval"
    r")\s*\(",
    flags=re.IGNORECASE,
)


def safe_relative_path(root: Path, requested: str | None) -> Path:
    root_resolved = root.resolve()
    candidate = root_resolved if requested is None else (root_resolved / requested).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafeOperation("path traversal outside the approved root is blocked") from exc
    return candidate


def validate_git_ref(value: str) -> str:
    if value.startswith("-") or not _GIT_REF.fullmatch(value):
        raise InvalidToolArguments("invalid Git revision")
    return value


def validate_readonly_sql(query: str) -> str:
    cleaned = _SQL_COMMENT.sub(" ", query).strip()
    if not cleaned:
        raise InvalidToolArguments("SQL query is empty")

    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    if ";" in cleaned:
        raise UnsafeOperation("multiple SQL statements are blocked")

    first = cleaned.split(None, 1)[0].upper()
    if first not in {"SELECT", "SHOW", "EXPLAIN"}:
        raise UnsafeOperation("only SELECT, SHOW, EXPLAIN, and EXPLAIN ANALYZE are allowed")

    if _FORBIDDEN_SQL.search(cleaned):
        raise UnsafeOperation("mutation or administrative SQL is blocked")
    if re.search(r"\bSELECT\b.*\bINTO\b", cleaned, flags=re.IGNORECASE | re.DOTALL):
        raise UnsafeOperation("SELECT INTO is blocked")
    if re.search(r"\bFOR\s+(UPDATE|NO\s+KEY\s+UPDATE|SHARE|KEY\s+SHARE)\b", cleaned, re.I):
        raise UnsafeOperation("row-locking SELECT statements are blocked")
    if _DANGEROUS_SQL.search(cleaned):
        raise UnsafeOperation("dangerous PostgreSQL functions are blocked")

    if first == "EXPLAIN":
        explain_tail = cleaned[len("EXPLAIN") :].lstrip()
        if explain_tail.upper().startswith("ANALYZE"):
            explain_tail = explain_tail[len("ANALYZE") :].lstrip()
        if not explain_tail.upper().startswith("SELECT"):
            raise UnsafeOperation("EXPLAIN is restricted to SELECT statements")

    return cleaned
