"""Store a feature requirement in the product_requirements audit table for
history maintenance -- a durable record of "what was asked for and when",
independent of chat history.

Usage:
    venv\\Scripts\\python.exe scripts\\store_requirement.py --title "..." --file path\\to\\text.txt [--status submitted] [--notes "..."]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.writer import insert_product_requirement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--file", required=True, type=Path, help="Path to a text file with the requirement content")
    parser.add_argument("--status", default="submitted", choices=["submitted", "planned", "in_progress", "shipped", "deferred"])
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    text = args.file.read_text(encoding="utf-8")
    row_id = insert_product_requirement(args.title, text, args.status, args.notes)
    print(f"Stored requirement id={row_id} title={args.title!r} status={args.status}")


if __name__ == "__main__":
    main()
