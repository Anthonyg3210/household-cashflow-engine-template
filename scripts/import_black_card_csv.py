#!/usr/bin/env python3
"""CLI: import Rewards Card / Travel Rewards (demo rewards card) CSV.

Usage:
  python scripts/import_black_card_csv.py /path/to/chase_card.csv
  python scripts/import_black_card_csv.py --csv /path/to/chase_card.csv --db data/cashflow.db

Replaces prior rows tagged source=chase_black_card ONLY.
Does not touch bank_csv, start_balance, or due-date learning.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import db
from engine.bank_import import BLACK_CARD_SOURCE, CSV_SOURCE, import_black_card_csv
from engine.seed_load import ensure_seeded


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Import Rewards Card card CSV as separate actuals")
    p.add_argument("csv", nargs="?", help="Path to Chase credit-card CSV")
    p.add_argument("--csv", dest="csv_opt", help="Path to Chase credit-card CSV (alt)")
    p.add_argument("--db", dest="db_path", default=str(ROOT / "data" / "cashflow.db"))
    p.add_argument(
        "--no-replace",
        action="store_true",
        help="Append without clearing prior chase_black_card actuals",
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

    before_csv = conn.execute(
        "SELECT COUNT(*) AS c FROM actuals WHERE source=?", (CSV_SOURCE,)
    ).fetchone()["c"]
    settings_before = {
        k: conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        for k in ("start_balance", "start_date", "end_date")
    }

    report = import_black_card_csv(conn, csv_path, replace=not args.no_replace)

    after_csv = conn.execute(
        "SELECT COUNT(*) AS c FROM actuals WHERE source=?", (CSV_SOURCE,)
    ).fetchone()["c"]
    after_card = conn.execute(
        "SELECT COUNT(*) AS c FROM actuals WHERE source=?", (BLACK_CARD_SOURCE,)
    ).fetchone()["c"]
    settings_after = {
        k: conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()["value"]
        for k in ("start_balance", "start_date", "end_date")
    }

    print(
        f"Imported {report['rows_imported']} {BLACK_CARD_SOURCE} rows "
        f"({report['pct_categorized']}% categorized) "
        f"{report['date_min']} → {report['date_max']}"
    )
    print(
        f"Purchases ${report['total_purchases']:,.2f} · "
        f"Payments ${report['total_payments']:,.2f} · "
        f"Returns ${report['total_returns']:,.2f} · "
        f"Net ${report['net']:,.2f}"
    )
    print("Top parents: " + ", ".join(f"{n} ${a:,.0f}" for n, a in (report["top_parents_by_spend"] or [])[:6]))
    print(
        "Uncategorized top: "
        + ", ".join(f"{m}×{c}" for m, c in report["top_uncategorized"][:6])
    )
    print(f"bank_csv before/after: {before_csv} / {after_csv} (must stay 1504)")
    print(f"chase_black_card: {after_card}")
    print(f"settings: {settings_after}")
    print(report.get("allowance_note") or "")
    if after_csv != before_csv:
        print("WARNING: bank_csv count changed — this should not happen", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
