"""One-time schema setup. Creates tables/indexes in the database named by
DATABASE_URL -- does NOT create the database or role itself; create those
yourself first (pgAdmin or psql), then put the connection string in .env.

Usage: venv\\Scripts\\python.exe db\\setup_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DB_SCHEMA
from db.connection import get_connection

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def main():
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql)
    print("Schema applied successfully.")

    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name", (DB_SCHEMA,))
        tables = [row[0] for row in cur.fetchall()]
    print(f"Tables in schema '{DB_SCHEMA}':", tables)


if __name__ == "__main__":
    main()
