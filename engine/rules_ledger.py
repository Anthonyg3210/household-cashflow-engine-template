"""Rules ledger drift check (generic). Read-only.

docs/DECISIONS_LEDGER.md is the one list of household rules. Each rule row names the test that enforces it. This module
checks, without editing anything, that:
  * every rule id is unique (R-01, R-02, ...),
  * every Active rule names a test as ``tests/test_x.py::test_name`` and that test function exists,
  * no picture, screenshot or real database file is tracked by git (they never belong in the repo).
Rules with status Pending (decided, not built yet) are listed as notes, not errors.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "DECISIONS_LEDGER.md"
ROW = re.compile(r"^\|\s*(R-\d{2,})\s*\|(.+)\|\s*$", re.M)
TEST_REF = re.compile(r"`(tests/[\w./-]+\.py)::(\w+)`")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp")
ALLOWED_TRACKED_DB = {"sample/demo_bootstrap.db"}  # synthetic demo only


def parse(path: Path = LEDGER) -> list[dict]:
    rows = []
    for m in ROW.finditer(path.read_text()):
        cells = [c.strip() for c in m.group(2).split("|")]
        rows.append({"id": m.group(1), "rule": cells[0] if cells else "", "status": (cells[1] if len(cells) > 1 else "").lower(),
                     "test": cells[2] if len(cells) > 2 else ""})
    return rows


def _functions(path: Path) -> set[str]:
    return {n.name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _tracked() -> list[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def check_forbidden_files_untracked(tracked: list[str] | None = None) -> list[str]:
    tracked = _tracked() if tracked is None else tracked
    bad = [f for f in tracked if f.lower().endswith(IMAGE_EXT) and not f.startswith("docs/assets/")]
    bad += [f for f in tracked if f.endswith(".db") and f not in ALLOWED_TRACKED_DB]
    return [f"tracked file must not be in git: {f}" for f in bad]


def findings(path: Path = LEDGER, tracked: list[str] | None = None) -> dict:
    rows = parse(path)
    errors, notes = [], []
    ids = [r["id"] for r in rows]
    for d in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"rule id {d} is used more than once")
    for r in rows:
        if r["status"].startswith("pending"):
            notes.append(f"{r['id']} is decided but not built yet: {r['rule']}")
            continue
        if not r["status"].startswith("active"):
            continue
        m = TEST_REF.search(r["test"])
        if not m:
            errors.append(f"{r['id']} has no enforcing test (`tests/test_x.py::test_name`)")
            continue
        f = ROOT / m.group(1)
        if not f.is_file() or m.group(2) not in _functions(f):
            errors.append(f"{r['id']} names {m.group(1)}::{m.group(2)}, which does not exist")
    errors += check_forbidden_files_untracked(tracked)
    return {"rules": len(rows), "errors": errors, "notes": notes}
