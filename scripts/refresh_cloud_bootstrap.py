#!/usr/bin/env python3
"""Refresh data/cloud_bootstrap.db from the live local data/cashflow.db.

Weekday backup / pre-push: run this so Streamlit Cloud gets current mitigations
and actuals on the next deploy (cashflow.db itself stays gitignored).

  python scripts/refresh_cloud_bootstrap.py
  git add data/cloud_bootstrap.db && git commit -m "Refresh cloud bootstrap DB" && git push
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "cashflow.db"
DST = ROOT / "data" / "cloud_bootstrap.db"


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: missing live DB: {SRC}", file=sys.stderr)
        return 1
    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, DST)
    size_kb = DST.stat().st_size / 1024
    print(f"OK: copied {SRC.name} → {DST.name} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
