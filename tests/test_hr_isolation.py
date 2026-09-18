"""HR-1 isolation guarantees.

These tests pin the boundary between the new HR capture pipeline and the
existing platform, in particular the frozen 11d-paper-v1 experiment:

* HR tables are separate and the HR DDL cannot touch existing objects;
* the existing schema, live loop, snapshot pipeline and every paper_trading
  source file are byte-identical to their committed content;
* the paper strategy hash and versions are unchanged;
* no import path exists in either direction;
* the existing pipeline and paper agent still import with HR broken;
* HR can only write hr_* tables and contains no order functionality.

If a later milestone deliberately changes a pinned production file, update
the pin in that milestone -- never to make HR-1 pass.
"""

import ast
import hashlib
import re
import subprocess
import sys
from pathlib import Path

from hr_capture.schema_guard import existing_table_names, load_schema_sql, strip_sql_comments, validate_hr_ddl

ROOT = Path(__file__).resolve().parent.parent
HR_DIR = ROOT / "hr_capture"
HR_SCRIPTS = [ROOT / "scripts" / name for name in ("run_hr_capture.py", "hr_setup_db.py", "run_hr_replay.py")]

# Line-ending-normalised SHA-256 of committed content at the HR-1 baseline (git HEAD 5b8a941).
FROZEN_FILES = {
    "db/schema.sql": "c3cf54ed2b23685def72a569876c8816d77c490d07f6c9c702b97b7358e3a37f",
    "paper_trading/__init__.py": "1098ab0a34a772ca46ecc278fd99260243ccda38092ad28dc66d0d9f227c5dac",
    "paper_trading/account.py": "915df9854fb82b6bd42866ed009929992baed1dbd50ed078322a2145cd0e7906",
    "paper_trading/agent.py": "96e30e430fffde5802164ab774d97d863675e487f65db431ff76862d90af0cc4",
    "paper_trading/broker.py": "888fa11b2ea665aa7100f8b28c19435483794b241043947688d0aa32e3e89dff",
    "paper_trading/config.py": "a47ca5e6fbcf0d8b47940b4dc76b3a4b590a874703ac8050a97036aa7c5f2bc3",
    "paper_trading/decision.py": "4c7f9a7914a1df35a90bada6d27ad09294c5bfc714c9d9059aceafa20a79c0ae",
    "paper_trading/journal.py": "6a71566df0fea771708dbbfa5c8d5e58f7b4d3a8c3405be59f2c129a6123fb57",
    "paper_trading/market_state.py": "f40154d45d936aa8418b02b9f764d810e76e7bc2ae0ae71501c9da56900e4f23",
    "paper_trading/models.py": "3d3ce36011813995f8603530d1dece0ca82f965e30576d4f20c20696b6492b15",
    "paper_trading/option_selection.py": "1bba0c2d89038aefc796a710b0b56fded75e8daa3bcbf78803a0d987713f8346",
    "paper_trading/position_manager.py": "4be80b29ecc1fcf89980303ee207be404e35ba4f3934892e61b22f3108fddd59",
    "paper_trading/risk.py": "af93a30c520f0ce231944ee98c2c0b43345b28a1a80f4523bc8aaaa11d6a9149",
    "paper_trading/safety.py": "bb18a201387d898a48dde21757a2f8246d35e646d057bba339ca6cab364aa77b",
    "paper_trading/tick.py": "a9d86f9de94d1446f69dcf3b85da0de12f4989a3612c35fec823504375f3fbc3",
    "paper_trading/trend_assessment.py": "033beba960a7d9bbf4037d92c58c015ed0d29df5b4986b99927b3fdda73a4cae",
    "pipeline/live_loop.py": "53a9371bdd9feefb975a7856783142907447c2ce05c1a737b7294156edeb41c6",
    "pipeline/run_snapshot.py": "256dfe7e3577bc9f0e35229ec21f49f5f6f76d1a41338645b32f2222f795de96",
}

FORBIDDEN_HR_IMPORTS = ("paper_trading", "pipeline.live_loop", "pipeline.run_snapshot", "pipeline.cas_live",
                        "dhan_client", "dhanhq", "backend", "option_chain.fetch", "db.writer", "db.connection")
ALLOWED_PROJECT_IMPORTS = ("hr_capture", "config.settings", "config.instruments", "pipeline.trading_calendar")
ORDER_FRAGMENTS = ("place_order", "modify_order", "cancel_order", "buy_order", "sell_order", "place_slice_order",
                   "super_order", "forever_order", "/orders", "orderupdate", "_order.py", "dhan_client")


def _normalised_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _hr_sources() -> list[Path]:
    return sorted(HR_DIR.glob("*.py")) + HR_SCRIPTS


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _code_strings(path: Path) -> list[str]:
    """String literals that are executable code (SQL etc.), excluding docstrings.
    Comments never appear in the AST, so they are excluded automatically."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def _code_identifiers(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.append(n.id)
        elif isinstance(n, ast.Attribute):
            names.append(n.attr)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(n.name)
        elif isinstance(n, ast.alias):
            names.append(n.name)
    return names


# 1 ---------------------------------------------------------------------------

def test_hr_ddl_only_creates_new_hr_objects():
    report = validate_hr_ddl(load_schema_sql())
    assert report["ok"], report["violations"]
    assert len(report["tables"]) == 7 and all(t.startswith("hr_") for t in report["tables"])
    assert all(i.startswith("hr_") and t.startswith("hr_") for i, t in report["indexes"])


def test_hr_tables_are_separate_from_existing_tables():
    existing = existing_table_names((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    assert not any(name.startswith("hr_") for name in existing)
    hr_ddl = strip_sql_comments(load_schema_sql()).lower()
    referenced = sorted(t for t in existing if re.search(rf"\b{t}\b", hr_ddl))
    assert referenced == [], f"HR DDL references existing tables: {referenced}"


# 2, 3, 4 -------------------------------------------------------------------

def test_frozen_production_files_are_unchanged():
    changed = {rel: _normalised_sha(ROOT / rel) for rel, expected in FROZEN_FILES.items()
               if _normalised_sha(ROOT / rel) != expected}
    assert changed == {}, f"frozen files modified: {sorted(changed)}"
    committed = {p.relative_to(ROOT).as_posix() for p in (ROOT / "paper_trading").glob("*.py")}
    assert committed == {k for k in FROZEN_FILES if k.startswith("paper_trading/")}, "paper_trading file set changed"


def test_paper_strategy_hash_and_versions_are_unchanged():
    from paper_trading.config import CONFIG_VERSION, DECISION_VERSION, DEFAULT_CONFIG, STRATEGY_VERSION
    assert STRATEGY_VERSION == "11d-paper-v1"
    assert DECISION_VERSION == "decision-v1" and CONFIG_VERSION == "config-v1"
    assert DEFAULT_CONFIG.config_hash() == "9c7c362d7e0c6a14"
    assert not any("hr" in field.lower().split("_") for field in DEFAULT_CONFIG.__dataclass_fields__)


# 5, 6 ----------------------------------------------------------------------

def test_hr_code_does_not_import_forbidden_platform_modules():
    for path in _hr_sources():
        for name in _imports(path):
            assert not any(name == f or name.startswith(f + ".") for f in FORBIDDEN_HR_IMPORTS), f"{path.name} imports {name}"
            top = name.split(".")[0]
            if (ROOT / top).is_dir() and top not in ("hr_capture",):
                assert any(name == a or name.startswith(a + ".") for a in ALLOWED_PROJECT_IMPORTS), \
                    f"{path.name} imports platform module {name} outside the allowed read-only set"


def test_no_existing_code_imports_hr_capture():
    hr_paths = set(_hr_sources())
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("venv/", "backend/venv/", "hr_capture/", "frontend/")) or path in hr_paths:
            continue
        if rel.startswith("tests/") and (path.name.startswith("test_hr_") or path.name == "hr_packet_factory.py"):
            continue
        if any(n == "hr_capture" or n.startswith("hr_capture.") for n in _imports(path)):
            offenders.append(rel)
    assert offenders == [], offenders


# 7, 19 ---------------------------------------------------------------------

def test_existing_pipeline_and_paper_agent_import_with_hr_broken():
    """A broken/absent HR package must not affect the live loop or the paper agent."""
    code = (
        "import sys, types\n"
        "broken = types.ModuleType('hr_capture')\n"
        "def _explode(name): raise RuntimeError('HR is broken')\n"
        "broken.__getattr__ = _explode\n"
        "sys.modules['hr_capture'] = broken\n"
        "import pipeline.live_loop, paper_trading.tick, paper_trading.agent, paper_trading.decision\n"
        "from paper_trading.config import DEFAULT_CONFIG\n"
        "assert DEFAULT_CONFIG.config_hash() == '9c7c362d7e0c6a14'\n"
        "print('ISOLATED_OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ISOLATED_OK" in result.stdout


def test_live_loop_and_paper_trading_have_no_hr_references():
    for rel in ("pipeline/live_loop.py", "pipeline/run_snapshot.py", *[p.relative_to(ROOT).as_posix()
                for p in (ROOT / "paper_trading").glob("*.py")]):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "hr_capture" not in text and not re.search(r"\bhr_[a-z]", text), rel


WRITE_SQL = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE|DROP\s+TABLE)\s+(\w+)",
                       re.IGNORECASE)


def test_hr_writes_only_hr_tables():
    write_targets = []
    for path in _hr_sources():
        for literal in _code_strings(path):
            for match in WRITE_SQL.finditer(literal):
                write_targets.append((path.name, match.group(1).upper(), match.group(2)))
    offenders = [t for t in write_targets if not t[2].lower().startswith("hr_")]
    assert offenders == [], offenders
    assert any(kind == "UPDATE" for _, kind, _ in write_targets), write_targets
    # INSERTs are built dynamically, only in db.insert_sql, which refuses any non-hr table
    # (tests/test_hr_session.py::test_writer_refuses_non_hr_tables).
    insert_builders = {p.name for p in _hr_sources() if any("INSERT INTO" in s.upper() for s in _code_strings(p))}
    assert insert_builders == {"db.py"}, insert_builders


def test_hr_reads_from_existing_tables_are_select_only():
    seen = 0
    for path in _hr_sources():
        for literal in _code_strings(path):
            for table in ("option_chain_raw", "raw_candles", "levels_snapshots", "paper_"):
                if re.search(rf"\bFROM\s+{table}", literal, re.IGNORECASE):
                    seen += 1
                    assert literal.strip().upper().startswith("SELECT"), f"{path.name}: {literal[:80]}"
    assert seen == 2   # option_chain_raw (universe resolution) and raw_candles (spot fallback)


# 18 ------------------------------------------------------------------------

def test_no_order_functionality_is_reachable_from_hr():
    for path in _hr_sources():
        code = " ".join(_code_identifiers(path) + _code_strings(path)).lower()
        for fragment in ORDER_FRAGMENTS:
            assert fragment not in code, f"{path.name} code contains {fragment!r}"


def test_hr_feed_only_builds_market_data_requests():
    from hr_capture.config import DISCONNECT_REQUEST_CODE, REQUEST_CODES
    assert set(REQUEST_CODES.values()) == {15, 17, 21} and DISCONNECT_REQUEST_CODE == 12
    for path in _hr_sources():
        imports = _imports(path)
        assert not any(n in ("requests", "urllib.request", "http.client", "httpx", "aiohttp") for n in imports), path.name
        urls = [s for s in _code_strings(path) if "://" in s]
        assert all(u.startswith("wss://api-feed.dhan.co") for u in urls), (path.name, urls)
