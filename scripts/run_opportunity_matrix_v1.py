"""Opportunity Matrix v1 research run (READ-ONLY). Artifacts -> data/cache/opportunity_matrix_v1/<run_id>/.

Usage: venv/Scripts/python.exe scripts/run_opportunity_matrix_v1.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opportunity_matrix_v1.run import main  # noqa: E402

if __name__ == "__main__":
    out, ds, res, audit = main()
    print("artifacts:", out)
    print("leakage audit:", audit["overall"])
