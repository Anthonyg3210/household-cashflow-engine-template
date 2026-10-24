#!/usr/bin/env python3
"""Apply Excel-parity overlays to the live twin DB without wiping actuals."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import db  # noqa: E402
from engine.excel_parity import apply_excel_parity  # noqa: E402


def main() -> None:
    conn = db.connect()
    db.init_db(conn)
    summary = apply_excel_parity(conn, prefer_single_mortgage=False, secondary_2028_inherit=False)
    print(summary)


if __name__ == "__main__":
    main()
