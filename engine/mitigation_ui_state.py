"""Dismiss / undismiss state for Dashboard mitigation Approve cards.

Stores skips in data/mitigation_dismissed.json as:
  { "YYYY-MM": {"dismissed_at": "...", "reason": "user"} }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
DISMISSED_PATH = ROOT / "data" / "mitigation_dismissed.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ym_key(year: int, month: int) -> str:
    return f"{int(year):04d}-{int(month):02d}"


def load_dismissed(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or DISMISSED_PATH
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_dismissed(data: dict[str, Any], path: Optional[Path] = None) -> None:
    p = path or DISMISSED_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def is_dismissed(year: int, month: int, path: Optional[Path] = None) -> bool:
    return _ym_key(year, month) in load_dismissed(path)


def dismiss_month(
    year: int,
    month: int,
    *,
    reason: str = "user",
    path: Optional[Path] = None,
) -> dict[str, Any]:
    data = load_dismissed(path)
    data[_ym_key(year, month)] = {
        "dismissed_at": _utc_now_iso(),
        "reason": reason or "user",
    }
    save_dismissed(data, path)
    return data


def undismiss_month(year: int, month: int, path: Optional[Path] = None) -> dict[str, Any]:
    data = load_dismissed(path)
    data.pop(_ym_key(year, month), None)
    save_dismissed(data, path)
    return data


def clear_dismissed_if_not_red(
    red_ym: set[tuple[int, int]],
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """Drop dismiss entries for months that are no longer red."""
    data = load_dismissed(path)
    keep: dict[str, Any] = {}
    for k, v in data.items():
        try:
            y, m = int(k[:4]), int(k[5:7])
        except (ValueError, IndexError):
            continue
        if (y, m) in red_ym:
            keep[k] = v
    if keep != data:
        save_dismissed(keep, path)
    return keep


def friendly_category_label(category: str) -> str:
    mapping = {
        "Jordan's Income": "Jordan's paycheck",
        "Alex's Income": "Alex's paycheck",
        "Savings": "Savings transfer",
        "Partner Allowance": "Wife's allowance",
    }
    return mapping.get(category, category)


def plain_english_mitigation(
    *,
    category: str,
    from_date,
    to_date,
    kind: str = "move",
) -> str:
    """partner-friendly one-liner without jargon."""
    from datetime import date as date_cls

    def _ord(d) -> str:
        if isinstance(d, date_cls):
            n = d.day
        else:
            n = int(str(d)[8:10])
        if 10 <= (n % 100) <= 20:
            suf = "th"
        else:
            suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suf}"

    label = friendly_category_label(category or "?")
    fr, to = _ord(from_date), _ord(to_date)
    if kind in ("income_pull", "pull_income"):
        return f"Move {label} from the {fr} to the {to}"
    if kind in ("move", "shift_flexible"):
        return f"Move {label} from the {fr} to the {to}"
    return f"Adjust {label} ({fr} → {to})"


def applied_checklist_line(entry: dict) -> str:
    """Short green checklist text, e.g. Done: Jan — Savings transfer moved later."""
    from calendar import month_abbr

    y, m = int(entry["year"]), int(entry["month"])
    mon = month_abbr[m]
    cat = friendly_category_label(entry.get("category") or "?")
    kind = entry.get("kind") or ""
    if kind in ("income_pull", "pull_income"):
        action = f"{cat} moved earlier"
    elif kind in ("move", "shift_flexible"):
        action = f"{cat} moved later"
    else:
        action = f"{cat} adjusted"
    return f"Done: {mon} — {action}"
