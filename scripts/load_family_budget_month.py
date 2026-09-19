#!/usr/bin/env python3
"""Load Budget workbook current-month forecast into planned_items + suppress rules.

Reads data/family_budget_sep2026_forecast.json (or re-extracts from workbook).
Does not touch bank_csv actuals or scenarios.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import db  # noqa: E402

DEFAULT_JSON = ROOT / "data" / "family_budget_sep2026_forecast.json"
SOURCE = "family_budget_sep2026_forecast"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--suppress-through", default="2026-09-30")
    args = ap.parse_args()

    payload = json.loads(args.json.read_text())
    items = payload["items"]
    source = payload.get("source") or SOURCE

    conn = db.connect()
    db.init_db(conn)
    cleared = db.clear_planned_by_source(conn, source)
    for it in items:
        db.add_planned(
            conn,
            {
                "date": it["date"],
                "amount": it["amount"],
                "category": it["category"],
                "label": it.get("label")
                or f"Budget workbook {it['date']} · {it['category']} (source={source})",
                "source": source,
                "enabled": True,
            },
        )
    db.set_setting(conn, "suppress_rules_through", args.suppress_through)
    # Preserve live seam
    db.set_setting(conn, "start_date", payload.get("start_date", "2026-09-12"))
    db.set_setting(conn, "start_balance", str(payload.get("start_balance", 5000.00)))

    print(
        f"Loaded {len(items)} planned ({source}); cleared {cleared}; "
        f"suppress_rules_through={args.suppress_through}"
    )


if __name__ == "__main__":
    main()
