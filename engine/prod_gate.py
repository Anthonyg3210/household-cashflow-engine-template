"""Pre-push / post-change integrity gate (generic household version).

A config or data edit can silently flip the forecast. Before and after any change that touches rules, planned items,
actuals or the starting balance:

    python -m engine.prod_gate --write-snapshot /tmp/before.json     # before the change
    python -m engine.prod_gate --compare-snapshot /tmp/before.json   # after the change

Plain ``python -m engine.prod_gate`` (what the pre-push hook runs) checks the current data only.
Exit 0 only when:
  * the projection runs and every month has numbers,
  * no planned item and actual are the same money counted twice (same date, amount and category),
  * (when comparing) every new red month or drop in the low point is explained by ``--accept "reason"``.
The gate works on a temporary COPY of the database; it never writes your data and never reboots the app.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import db
from .project import project

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "cashflow.db"
FALLBACK_DB = ROOT / "sample" / "demo_bootstrap.db"
LOW_POINT_TOLERANCE = 1.00  # dollars of drift in the low point allowed without an explanation


def _red_months(months: list[dict]) -> list[str]:
    return [f"{int(m['year']):04d}-{int(m['month']):02d}" for m in months or []
            if (m.get("days_negative") or 0) > 0]


def _project(conn) -> dict:
    s = db.get_settings(conn)
    actuals = [a for a in db.list_actuals(conn) if (a.get("source") or "") != "rewards_card"]
    return project(s["start_date"], s["end_date"], s["start_balance"], db.list_rules(conn), db.list_planned(conn),
                   actuals, None, s["warning_threshold"], suppress_rules_through=s.get("suppress_rules_through"))


def double_counts(conn) -> list[str]:
    """Planned items that duplicate an actual (same date, amount to the cent, category)."""
    key = lambda r: (str(r.get("date"))[:10], round(float(r.get("amount") or 0), 2), (r.get("category") or "").strip().lower())
    acts = Counter(key(a) for a in db.list_actuals(conn))
    out = []
    for p in db.list_planned(conn):
        if p.get("enabled", 1) in (0, False):
            continue
        k = key(p)
        if acts.get(k):
            out.append(f"{k[0]} {k[2] or '(no category)'} {k[1]:,.2f} is both planned and actual")
    return out


def capture_snapshot(conn, *, label: Optional[str] = None) -> dict[str, Any]:
    res = _project(conn)
    s = res["summary"]
    return {"label": label, "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "start_balance": round(float(s["start_balance"]), 2), "ending_balance": round(float(s["ending_balance"]), 2),
            "min_eod": round(float(s["min_eod"]), 2), "min_eod_date": str(s["min_eod_date"]),
            "red_months": _red_months(res["months"]), "months": len(res["months"])}


def compare(before: dict, after: dict, accept: Optional[str] = None) -> list[str]:
    problems = []
    new_red = sorted(set(after["red_months"]) - set(before["red_months"]))
    if new_red:
        problems.append(f"new red month(s): {', '.join(new_red)}")
    if after["min_eod"] < before["min_eod"] - LOW_POINT_TOLERANCE:
        problems.append(f"low point fell from {before['min_eod']:,.2f} to {after['min_eod']:,.2f}")
    if after["months"] != before["months"]:
        problems.append(f"forecast length changed ({before['months']} -> {after['months']} months)")
    if problems and accept:
        return []
    return problems


def run(db_path: Optional[Path] = None, *, compare_to: Optional[dict] = None, accept: Optional[str] = None) -> tuple[int, dict, list[str]]:
    src = Path(db_path) if db_path else (DEFAULT_DB if DEFAULT_DB.exists() else FALLBACK_DB)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "gate.db"
        shutil.copy2(src, tmp)
        conn = db.connect(tmp, restore_bootstrap=False)
        try:
            db.init_db(conn)
            snap = capture_snapshot(conn)
            problems = double_counts(conn)
            if not snap["months"]:
                problems.append("projection produced no months")
            if compare_to is not None:
                problems += compare(compare_to, snap, accept)
        finally:
            conn.close()
    return (1 if problems else 0), snap, problems


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path)
    ap.add_argument("--write-snapshot", type=Path)
    ap.add_argument("--compare-snapshot", type=Path)
    ap.add_argument("--accept", help="plain-English reason a new red month / lower low point is intended")
    a = ap.parse_args(argv)
    before = json.loads(a.compare_snapshot.read_text()) if a.compare_snapshot else None
    rc, snap, problems = run(a.db, compare_to=before, accept=a.accept)
    if a.write_snapshot:
        a.write_snapshot.write_text(json.dumps(snap, indent=2) + "\n")
    print(f"prod_gate: low point {snap['min_eod']:,.2f} on {snap['min_eod_date']}; red months: "
          f"{', '.join(snap['red_months']) or 'none'}")
    for p in problems:
        print(f"prod_gate: PROBLEM {p}")
    if a.accept and before is not None:
        print(f"prod_gate: accepted change: {a.accept}")
    print("prod_gate: PASS" if rc == 0 else "prod_gate: FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
