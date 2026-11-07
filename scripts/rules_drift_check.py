#!/usr/bin/env python3
"""Rules ledger drift check. Read-only.

  python scripts/rules_drift_check.py          # plain-English findings; exit 1 on any drift, 0 when clean
  python scripts/rules_drift_check.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import rules_ledger  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    f = rules_ledger.findings()
    if a.json:
        print(json.dumps(f, indent=2))
    else:
        print(f"Rules ledger: {f['rules']} rules.")
        for e in f["errors"]:
            print(f"DRIFT: {e}")
        for n in f["notes"]:
            print(f"NOTE: {n}")
        print("Clean: no drift." if not f["errors"] else f"{len(f['errors'])} drift finding(s). Fix the code or record the decision; never loosen a test.")
    return 1 if f["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
