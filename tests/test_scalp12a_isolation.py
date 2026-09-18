"""12A isolation guarantees (extends the HR-1 isolation pins).

12A-scalp-v1 is a separate EXPERIMENT beside the frozen 11d-paper-v1 CONTROL:

* every 11D / pipeline file pinned by HR-1 is still byte-identical;
* the 11D strategy version, config version and hash are unchanged;
* the HR capture package is byte-identical (12A must not bend HR to its needs);
* 12A has its own version and a different config hash;
* 12A imports nothing from paper_trading, the live loop, Dhan clients or HR internals,
  and nothing in the platform imports 12A;
* 12A SQL writes only scalp12a_* tables and contains no order functionality.
"""

import ast
import hashlib
import re
from pathlib import Path

from tests.test_hr_isolation import FROZEN_FILES, ORDER_FRAGMENTS

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "scalp_12a"
SCRIPTS = [ROOT / "scripts" / n for n in ("run_scalp12a_shadow.py", "run_scalp12a_research.py", "scalp12a_setup_db.py")]

# HR-1 package as validated live on 2026-09-15 .. 09-18 (line-ending-normalised SHA-256).
FROZEN_HR_FILES = {
    "hr_capture/__init__.py": "ad160c6b20e4dece92d83da05942dda608a40c20fef9a6a5491a15ee2a70fcef",
    "hr_capture/aggregator.py": "f082b0c49e36b1f84ae417a6c45759429081acd2648ab9f4fa38436347818bea",
    "hr_capture/bars.py": "41c8680f5893d2dd5c1fa81d9544232ee22eb569eaf837907959d59166bd0df5",
    "hr_capture/chain_state.py": "bc92cf11dbac8f230363e20efc7134dfbdb27bdc0f7957381b94f40936980e2c",
    "hr_capture/config.py": "2fc3cd0ddfcab44379b915de235e3eafe9d8d0f668d8447d376c03c07941f8fc",
    "hr_capture/db.py": "98c6b911810c46fbadd8ac5af0d9a7ad90d93ba49bbc9500e414cde24f349d8d",
    "hr_capture/feed.py": "2d004898f3353811d551a77d3e5c20de9f54fa4f40e5436dfe31646412253f01",
    "hr_capture/market_state.py": "fdd59e89a803504a3fd2446e081db8f81b2e734a777a685e0da39554c53214e2",
    "hr_capture/option_state.py": "e31aa5456abab14b1df4663c60f08c877ffe1b279bdcc2d7192e652a27b5761b",
    "hr_capture/protocol.py": "a4b6180c5407063fe2c8a89230976ad12ad5f17d9d5a2669d777b6ac3b7202b3",
    "hr_capture/recorder.py": "0b9311b81f37afe7283cbd2f8406045ea1ae527ed141cc625ddff91f38879f1e",
    "hr_capture/runner.py": "6e122589a1803668e9f6215fa586a8fcbbb8887b7b202a6ccfc7fc79eff603c3",
    "hr_capture/schema_guard.py": "61d5b748c0444c3a30adb85e94ca4ad8dd5acdfe8fae46a49157e286418ed0fb",
    "hr_capture/service.py": "bdf9a407a2c196aa6fd6e5b98bd1027f1de93cc2b64fe8bb1f6aebbd49965f04",
    "hr_capture/timeutil.py": "f17dd05d973e1cc40b99f3ed23f096afadddd1015256d2db68cbd6c66e7ec8ea",
    "hr_capture/universe.py": "a8214c4dfc33dd2e5d84fc5eca1e4b5d782261b0b28b7788afd64394474b2903",
    "hr_capture/writer.py": "a984eb3b387792e9e89ee92bbbd5476c5dc5a2cfda33acbd14c4f16fefd3a654",
    "hr_capture/schema.sql": "7ab8d463ab49d9f9abe6d325551f422c867a331ce59214df0718ebdf3c9f2f02",
}

FORBIDDEN_12A_IMPORTS = ("paper_trading", "pipeline.live_loop", "pipeline.run_snapshot", "pipeline.cas_live",
                         "dhan_client", "dhanhq", "backend", "option_chain.fetch", "db.writer",
                         "hr_capture.feed", "hr_capture.writer", "hr_capture.service", "hr_capture.runner",
                         "hr_capture.db", "hr_capture.recorder", "websockets")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _sources() -> list[Path]:
    return sorted(PKG.glob("*.py")) + [p for p in SCRIPTS if p.exists()]


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_11d_and_pipeline_files_unchanged():
    for rel, digest in FROZEN_FILES.items():
        assert _sha(ROOT / rel) == digest, f"{rel} changed -- 11D control must stay frozen"


def test_11d_strategy_version_and_hash_unchanged():
    from paper_trading.config import CONFIG_VERSION, DECISION_VERSION, DEFAULT_CONFIG, STRATEGY_VERSION
    assert (STRATEGY_VERSION, DECISION_VERSION, CONFIG_VERSION) == ("11d-paper-v1", "decision-v1", "config-v1")
    assert DEFAULT_CONFIG.config_hash() == "9c7c362d7e0c6a14"


def test_hr_capture_package_unchanged():
    for rel, digest in FROZEN_HR_FILES.items():
        assert _sha(ROOT / rel) == digest, f"{rel} changed -- 12A must not modify HR capture"


def test_12a_has_its_own_version_and_hash():
    from paper_trading.config import DEFAULT_CONFIG as C11
    from scalp_12a.config import DEFAULT_CONFIG, STRATEGY_VERSION, ScalpConfig
    assert STRATEGY_VERSION == "12A-scalp-v1"
    h = DEFAULT_CONFIG.config_hash()
    assert re.fullmatch(r"[0-9a-f]{16}", h) and h != C11.config_hash()
    assert ScalpConfig().config_hash() == h                     # deterministic
    assert ScalpConfig(stop_pct=6.0).config_hash() != h         # sensitive to every value


def test_12a_does_not_import_forbidden_modules():
    for path in _sources():
        for name in _imports(path):
            assert not any(name == f or name.startswith(f + ".") for f in FORBIDDEN_12A_IMPORTS), (path, name)


def test_no_platform_code_imports_12a():
    for folder in ("paper_trading", "pipeline", "hr_capture", "backend/app", "db", "market_transition", "analytics"):
        for path in (ROOT / folder).rglob("*.py"):
            if "venv" in path.parts:
                continue
            for name in _imports(path):
                assert not name.startswith("scalp_12a"), (path, name)


def _sql_text() -> str:
    text = (PKG / "schema.sql").read_text(encoding="utf-8")
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text += "\n" + node.value
            elif isinstance(node, ast.JoinedStr):
                text += "\n" + "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    return text


def test_12a_writes_only_scalp12a_tables():
    sql = _sql_text()
    targets = re.findall(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE|TRUNCATE"
                         r"|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|CREATE\s+INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+\w+\s+ON)"
                         r"\s+(\w+)", sql)   # SQL is written in upper case
    targets = [t for t in targets if t.upper() not in ("SET",)]
    assert targets, "expected to find 12A write statements"
    for t in targets:
        assert t.startswith("scalp12a_"), f"12A must only write scalp12a_* tables, found {t}"


def test_no_order_functionality_in_12a():
    for path in _sources() + [PKG / "schema.sql"]:
        text = path.read_text(encoding="utf-8").lower()
        for fragment in ORDER_FRAGMENTS:
            assert fragment not in text, (path, fragment)


def test_12a_config_carries_the_expiry_veto():
    from scalp_12a.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG.expiry_close_veto_start == "15:15:00"
    assert DEFAULT_CONFIG.expiry_transition_zone_start <= "15:14:00"
    assert DEFAULT_CONFIG.mode_b_tradeable is False
