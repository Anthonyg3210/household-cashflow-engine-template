#!/usr/bin/env python3
"""Build a tiny demo SQLite DB from synthetic seed (no personal data).

Usage:
  python scripts/seed_demo.py
  streamlit run app.py

Creates/refreshes:
  data/cashflow.db           (runtime; gitignored)
  sample/demo_bootstrap.db   (tiny demo copy under sample/)
  data/cloud_bootstrap.db    (gitignored local bootstrap for first boot)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import db
from engine.seed_load import LOCAL_SEED, import_seed


def main() -> int:
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if not (LOCAL_SEED / "rules.json").exists():
        print("ERROR: seed/rules.json missing", file=sys.stderr)
        return 1

    db_path = data_dir / "cashflow.db"
    bootstrap = data_dir / "cloud_bootstrap.db"
    for p in (db_path, bootstrap):
        if p.exists():
            p.unlink()

    # Connect without restoring bootstrap (file absent)
    conn = db.connect(db_path)
    try:
        db.init_db(conn)
        summary = import_seed(
            conn,
            LOCAL_SEED,
            prefer_single_mortgage=False,
            secondary_2028_inherit=False,
            reset=True,
        )
    finally:
        conn.close()

    sample_dir = ROOT / "sample"
    sample_dir.mkdir(parents=True, exist_ok=True)
    demo_boot = sample_dir / "demo_bootstrap.db"
    shutil.copy2(db_path, demo_boot)
    shutil.copy2(db_path, bootstrap)

    debts_src = ROOT / "sample" / "fixtures" / "synthetic" / "debts.json"
    debts_dst = data_dir / "debts.json"
    if debts_src.exists():
        shutil.copy2(debts_src, debts_dst)

    print("Demo DB ready:")
    print(f"  {db_path}")
    print(f"  {demo_boot}")
    print(f"  rules_imported={summary.get('rules_imported')} start_balance={summary.get('start_balance')}")
    print("Run: streamlit run app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
