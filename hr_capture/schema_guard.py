"""Static validation of hr_capture/schema.sql.

The DDL may only create new ``hr_*`` tables and ``hr_*`` indexes on ``hr_*``
tables. Anything that could touch an existing object -- ALTER, DROP,
TRUNCATE, DML, grants, foreign keys, views, functions, triggers, schemas or
extensions -- is rejected before the file can be applied.
"""

import re
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

FORBIDDEN_KEYWORDS = (
    "ALTER", "DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT", "GRANT", "REVOKE",
    "RENAME", "REFERENCES", "FOREIGN", "VIEW", "FUNCTION", "TRIGGER", "PROCEDURE",
    "SCHEMA", "EXTENSION", "RULE", "POLICY", "COMMENT ON", "OWNER",
)

_CREATE_TABLE = re.compile(r"^CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\(", re.IGNORECASE)
_CREATE_INDEX = re.compile(
    r"^CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+ON\s+(\w+)\s*\(", re.IGNORECASE
)


def strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def split_statements(sql: str) -> list[str]:
    return [s.strip() for s in strip_sql_comments(sql).split(";") if s.strip()]


def validate_hr_ddl(sql: str) -> dict:
    """Returns {"ok", "tables", "indexes", "violations"}."""
    violations: list[str] = []
    tables: list[str] = []
    indexes: list[tuple[str, str]] = []

    for stmt in split_statements(sql):
        flat = " ".join(stmt.split())
        upper = flat.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{keyword}\b", upper):
                violations.append(f"forbidden keyword {keyword!r} in: {flat[:90]}")
        table_match = _CREATE_TABLE.match(flat)
        index_match = _CREATE_INDEX.match(flat)
        if table_match:
            name = table_match.group(1)
            if not name.lower().startswith("hr_"):
                violations.append(f"table without hr_ prefix: {name}")
            tables.append(name)
        elif index_match:
            index_name, on_table = index_match.group(1), index_match.group(2)
            if not index_name.lower().startswith("hr_"):
                violations.append(f"index without hr_ prefix: {index_name}")
            if not on_table.lower().startswith("hr_"):
                violations.append(f"index {index_name} targets non-hr table: {on_table}")
            indexes.append((index_name, on_table))
        else:
            violations.append(f"statement is not CREATE TABLE/INDEX IF NOT EXISTS: {flat[:90]}")

    return {"ok": not violations, "tables": tables, "indexes": indexes, "violations": violations}


def existing_table_names(existing_schema_sql: str) -> set[str]:
    """Table names created by the platform's existing db/schema.sql."""
    return {
        m.group(1).lower()
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", strip_sql_comments(existing_schema_sql), re.IGNORECASE)
    }


def load_schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")
