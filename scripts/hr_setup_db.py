"""HR-1 DDL: validate (default) or apply (--apply) hr_capture/schema.sql.

Validation is static (hr_capture/schema_guard.py) and must pass before
anything is applied. On --apply the script snapshots the structure of every
pre-existing table (columns, indexes, constraints) before and after, and
reports whether anything other than new hr_* objects changed.

Usage:
    venv\\Scripts\\python.exe scripts\\hr_setup_db.py            # validate only
    venv\\Scripts\\python.exe scripts\\hr_setup_db.py --apply    # validate, then apply
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hr_capture import db as hr_db
from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.schema_guard import existing_table_names, load_schema_sql, validate_hr_ddl

STRUCTURE_SQL = {
    "columns": """SELECT table_name, column_name, data_type, is_nullable, coalesce(column_default, ''), ordinal_position
                  FROM information_schema.columns WHERE table_schema = current_schema() ORDER BY 1, 6""",
    "indexes": "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() ORDER BY 1, 2",
    "constraints": """SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint
                      WHERE connamespace = (SELECT oid FROM pg_namespace WHERE nspname = current_schema()) ORDER BY 1, 2""",
}


def structure(conn, exclude_hr: bool) -> dict:
    snap = {}
    with conn.cursor() as cur:
        for name, sql in STRUCTURE_SQL.items():
            cur.execute(sql)
            rows = [[str(v) for v in r] for r in cur.fetchall()]
            snap[name] = [r for r in rows if not (exclude_hr and r[0].split(".")[-1].startswith("hr_"))]
    return snap


def digest(snap: dict) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    sql = load_schema_sql()
    report = validate_hr_ddl(sql)
    existing = existing_table_names((Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text(encoding="utf-8"))
    overlap = sorted(existing & {t.lower() for t in report["tables"]})
    print("DDL validation:", "PASS" if report["ok"] and not overlap else "FAIL")
    print("  tables  :", report["tables"])
    print("  indexes :", [name for name, _ in report["indexes"]])
    print("  overlap with existing db/schema.sql tables:", overlap or "none")
    for violation in report["violations"]:
        print("  VIOLATION:", violation)
    if not report["ok"] or overlap:
        return 1
    if not args.apply:
        print("Validation only. Re-run with --apply to create the hr_* tables.")
        return 0

    conn = hr_db.connect(DEFAULT_HR_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_schema(), current_user")
            print("Target schema/role:", cur.fetchone())
        before = structure(conn, exclude_hr=True)
        with conn.cursor() as cur:
            cur.execute(sql)
        after = structure(conn, exclude_hr=True)
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
                        "AND table_name LIKE 'hr\\_%%' ORDER BY 1")
            hr_tables = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    unchanged = digest(before) == digest(after)
    print("Applied. hr_* tables now present:", hr_tables)
    print("Pre-existing structure digest before:", digest(before))
    print("Pre-existing structure digest after :", digest(after))
    print("Pre-existing tables/indexes/constraints unchanged:", unchanged)
    return 0 if unchanged else 2


if __name__ == "__main__":
    raise SystemExit(main())
