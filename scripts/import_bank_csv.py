#!/usr/bin/env python3
"""CLI: import bank CSV into household cashflow engine actuals.

Usage:
  python scripts/import_bank_csv.py /path/to/chase.csv --mode merge
  python scripts/import_bank_csv.py /path/to/chase.csv --mode replace --confirm-replace
  python scripts/import_bank_csv.py --csv /path/to/chase.csv --db data/cashflow.db

Merge skips duplicate fingerprints. Replace clears source=bank_csv after confirm
and a timestamped household backup. Does not wipe recurring_rules or scenarios.
Writes data/import_report.md and refreshes data/merchant_map.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import db
from engine.bank_import import import_csv, preview_csv_import, write_import_report
from engine.seed_load import ensure_seeded


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Import bank CSV as actuals")
    p.add_argument("csv", nargs="?", help="Path to bank CSV")
    p.add_argument("--csv", dest="csv_opt", help="Path to bank CSV (alt)")
    p.add_argument("--db", dest="db_path", default=str(ROOT / "data" / "cashflow.db"))
    p.add_argument(
        "--mode",
        choices=("merge", "replace"),
        default=None,
        help="merge (skip dupes) or replace (clear bank_csv). Default: replace",
    )
    p.add_argument(
        "--confirm-replace",
        action="store_true",
        help="Required with --mode replace",
    )
    p.add_argument(
        "--preview-only",
        action="store_true",
        help="Print preview and exit without writing",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip timestamped backup before replace",
    )
    p.add_argument(
        "--no-replace",
        action="store_true",
        help="Deprecated alias for --mode merge",
    )
    args = p.parse_args(argv)
    csv_path = args.csv_opt or args.csv
    if not csv_path:
        p.error("CSV path required")
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    mode = args.mode
    if mode is None:
        mode = "merge" if args.no_replace else "replace"

    conn = db.connect(Path(args.db_path), restore_bootstrap=False)
    ensure_seeded(conn)

    if args.preview_only:
        prev = preview_csv_import(conn, csv_path)
        print(
            f"Preview: {prev['rows_parsed']} rows · "
            f"{prev['date_min']}→{prev['date_max']} · "
            f"{prev['pct_categorized']}% categorized · "
            f"new={prev['new_row_count']} dupes={prev['duplicate_count']} · "
            f"overlap={prev['overlap']} short_history={prev['short_history_warning']}"
        )
        if prev.get("overlap_note"):
            print(prev["overlap_note"])
        if prev.get("short_history_message"):
            print(prev["short_history_message"])
        return 0

    if mode == "replace" and not args.confirm_replace:
        print(
            "Replace is destructive. Re-run with --confirm-replace after --preview-only.",
            file=sys.stderr,
        )
        return 2

    report = import_csv(
        conn,
        csv_path,
        mode=mode,
        confirm_replace=(mode == "replace" and args.confirm_replace),
        create_backup=not args.no_backup,
        root=ROOT,
    )
    settings = db.get_settings(conn)
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
    cr = report.get("change_report") or {}
    print(
        f"Mode={report['mode']}: inserted {report['rows_imported']} "
        f"(skipped dupes {report.get('rows_skipped_duplicates', 0)}, "
        f"cleared {report.get('rows_cleared', 0)}). "
        f"{report['pct_categorized']}% categorized. actuals in DB: {n}. Report: {out}"
    )
    if (report.get("backup") or {}).get("path"):
        print(f"Backup: {report['backup']['path']}")
    print("Change:", cr)
    print(
        "Uncategorized top: "
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
