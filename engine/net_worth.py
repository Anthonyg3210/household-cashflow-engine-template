"""Optional net-worth / brokerage / savings snapshot for pictorial cards.

Balances are *not* part of the cash-flow twin start_balance. They are display-only
figures Alex can paste later (Fidelity brokerage, household savings).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = _ROOT / "data" / "net_worth_snapshot.json"

_EMPTY = {
    "fidelity_brokerage_balance": None,
    "savings_balance": None,
    "balances_as_of": None,
}


def snapshot_path() -> Path:
    return SNAPSHOT_PATH


def load_snapshot(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or SNAPSHOT_PATH
    out = dict(_EMPTY)
    if not p.exists():
        return out
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(raw, dict):
        return out
    for key in ("fidelity_brokerage_balance", "savings_balance"):
        val = raw.get(key, None)
        if val is None or val == "":
            out[key] = None
        else:
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                out[key] = None
    as_of = raw.get("balances_as_of")
    out["balances_as_of"] = (str(as_of).strip() or None) if as_of not in (None, "") else None
    return out


def save_snapshot(
    *,
    fidelity_brokerage_balance: Optional[float] = None,
    savings_balance: Optional[float] = None,
    balances_as_of: Optional[str] = None,
    path: Optional[Path] = None,
    clear_empty: bool = True,
) -> dict[str, Any]:
    """Persist balances. Empty / None stays null so UI shows intentional placeholder."""
    p = path or SNAPSHOT_PATH
    existing = load_snapshot(p)

    def _norm_bal(v, fallback):
        if v is None and not clear_empty:
            return fallback
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    payload = {
        "fidelity_brokerage_balance": _norm_bal(
            fidelity_brokerage_balance, existing.get("fidelity_brokerage_balance")
        ),
        "savings_balance": _norm_bal(savings_balance, existing.get("savings_balance")),
        "balances_as_of": (
            (str(balances_as_of).strip() or None)
            if balances_as_of is not None
            else existing.get("balances_as_of")
        ),
        "note": "Optional household balances for pictorial cards. Leave null until Alex pastes figures in Settings.",
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return load_snapshot(p)


def format_balance_display(value: Optional[float], *, empty: str = "—") -> str:
    """Intentional blank: em dash (or 'Not set yet'), never a broken $0.00."""
    if value is None:
        return empty
    return f"${float(value):,.2f}"
