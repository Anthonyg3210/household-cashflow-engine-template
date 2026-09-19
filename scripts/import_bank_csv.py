#!/usr/bin/env python3
"""CLI: import bank CSV into household cashflow engine actuals.

Usage:
  python scripts/import_bank_csv.py /path/to/chase.csv
  python scripts/import_bank_csv.py --csv /path/to/chase.csv --db data/cashflow.db

Replaces prior rows tagged source=bank_csv. Does not wipe recurring_rules or scenarios.
Writes data/import_report.md and refreshes data/merchant_map.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import db
from engine.bank_import import import_csv, write_import_report
from engine.seed_load import ensure_seeded


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Import bank CSV as actuals")
    p.add_argument("csv", nargs="?", help="Path to bank CSV")
    p.add_argument("--csv", dest="csv_opt", help="Path to bank CSV (alt)")
    p.add_argument("--db", dest="db_path", default=str(ROOT / "data" / "cashflow.db"))
    p.add_argument(
        "--no-replace",
        action="store_true",
        help="Append without clearing prior bank_csv actuals",
    )
    args = p.parse_args(argv)
    csv_path = args.csv_opt or args.csv
    if not csv_path:
        p.error("CSV path required")
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    conn = db.connect(Path(args.db_path))
    ensure_seeded(conn)
    # Preserve required projection settings
    db.set_setting(conn, "start_balance", "5000.00")
    db.set_setting(conn, "start_date", "2026-09-12")
    db.set_setting(conn, "end_date", "2029-09-12")

    report = import_csv(conn, csv_path, replace_csv_actuals=not args.no_replace)
    settings = db.get_settings(conn)
    # get_settings returns parsed types; stringify for report
    settings_out = {
        "start_balance": settings["start_balance"],
        "start_date": settings["start_date"].isoformat()
        if hasattr(settings["start_date"], "isoformat")
        else settings["start_date"],
        "end_date": settings["end_date"].isoformat()
        if hasattr(settings["end_date"], "isoformat")
        else settings["end_date"],
    }
    out = ROOT / "data" / "import_report.md"
    write_import_report(report, settings_out, out)

    n = conn.execute("SELECT COUNT(*) AS c FROM actuals").fetchone()["c"]
    print(
        f"Imported {report['rows_imported']} rows "
        f"({report['pct_categorized']}% categorized). "
        f"actuals in DB: {n}. Report: {out}"
    )
    print(
        f"Uncategorized top: "
        + ", ".join(f"{m}×{c}" for m, c in report["top_uncategorized"][:5])
    )
    ddl = report.get("due_date_learn") or {}
    if ddl.get("error"):
        print(f"due_date_learn warning: {ddl['error']}")
    elif ddl:
        print(
            "due_date_learn: "
            f"{ddl.get('applied_rule_changes', 0)} rule DOM updates "
            f"(eligible {ddl.get('eligible')})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
