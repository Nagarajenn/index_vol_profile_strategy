"""Create the 12A shadow/research tables (scalp12a_* only; idempotent).

Usage: venv\\Scripts\\python.exe scripts\\scalp12a_setup_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scalp_12a import db  # noqa: E402


def main() -> None:
    with db.connect() as conn:
        db.apply_schema(conn)
        rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'scalp12a_%' "
                            "ORDER BY 1").fetchall()
    print("12A tables:", [r[0] for r in rows])


if __name__ == "__main__":
    main()
