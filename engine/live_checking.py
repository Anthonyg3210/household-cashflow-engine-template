"""Durable live-checking balance + note sync.

Always use set_live_checking — never write balance without refreshing the note.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from engine.db import init_db, set_setting

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LABEL = "TOTAL CHECKING (...0000)"
_SETTING_KEYS = (
    "live_checking_balance",
    "live_checking_as_of",
    "live_checking_label",
    "live_checking_note",
)


def _root(root: Optional[Path | str] = None) -> Path:
    return Path(root) if root is not None else _ROOT


def _data_dir(root: Optional[Path | str] = None) -> Path:
    return _root(root) / "data"


def _json_path(root: Optional[Path | str] = None) -> Path:
    return _data_dir(root) / "live_checking.json"


def _cashflow_db_path(root: Optional[Path | str] = None) -> Path:
    return _data_dir(root) / "cashflow.db"


def _bootstrap_db_path(root: Optional[Path | str] = None) -> Path:
    return _data_dir(root) / "cloud_bootstrap.db"


def _format_balance(balance: float) -> str:
    return f"{float(balance):.2f}"


def _format_money(amount: float) -> str:
    """Signed currency like $1,234.56 or -$40.20."""
    amt = float(amount)
    if amt < 0:
        return f"-${abs(amt):,.2f}"
    return f"${amt:,.2f}"


def _auto_note(balance: float, as_of: str, pending: Optional[list] = None) -> str:
    bal = float(balance)
    lines = [
        f"Chase available ${bal:,.2f} as of {as_of}. Pending already reduces available."
    ]
    if pending:
        for item in pending:
            if not isinstance(item, dict):
                continue
            desc = str(item.get("desc") or item.get("description") or "").strip()
            try:
                amt = float(item.get("amount") or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if desc:
                lines.append(f"{desc} {_format_money(amt)}")
            else:
                lines.append(_format_money(amt))
    return "\n".join(lines)


def _normalize_amount_text(text: str) -> str:
    return str(text).replace("$", "").replace(",", "")


def _open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _write_db_settings(
    path: Path,
    *,
    balance: float,
    as_of: str,
    label: str,
    note: str,
) -> None:
    conn = _open_db(path)
    try:
        set_setting(conn, "live_checking_balance", _format_balance(balance))
        set_setting(conn, "live_checking_as_of", str(as_of))
        set_setting(conn, "live_checking_label", str(label))
        set_setting(conn, "live_checking_note", str(note))
    finally:
        conn.close()


def _read_db_settings(path: Path) -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {k: None for k in _SETTING_KEYS}
    if not path.exists():
        return out
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'live_checking%'"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return out
    for row in rows:
        if row["key"] in out:
            out[row["key"]] = row["value"]
    return out


def set_live_checking(
    balance: float,
    as_of: str,
    note: Optional[str] = None,
    pending: Optional[list] = None,
    label: str = _DEFAULT_LABEL,
    source: Optional[str] = None,
    prior_available: Optional[float] = None,
    root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Write live checking balance and keep the note in sync everywhere.

    Always use set_live_checking — never write balance without refreshing the note.

    Persists:
      - data/live_checking.json
      - settings on data/cashflow.db and data/cloud_bootstrap.db
        (live_checking_balance, live_checking_as_of, live_checking_label,
         live_checking_note)
    """
    bal = float(balance)
    as_of_s = str(as_of)
    label_s = str(label) if label is not None else _DEFAULT_LABEL
    pending_list = list(pending) if pending is not None else []
    note_s = note if note is not None else _auto_note(bal, as_of_s, pending_list)

    payload: dict[str, Any] = {
        "balance": bal,
        "label": label_s,
        "as_of": as_of_s,
        "as_of_note": note_s,
    }
    if source is not None:
        payload["source"] = source
    if prior_available is not None:
        payload["prior_available"] = float(prior_available)
    if pending is not None:
        payload["pending"] = pending_list

    data_dir = _data_dir(root)
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = _json_path(root)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    _write_db_settings(
        _cashflow_db_path(root),
        balance=bal,
        as_of=as_of_s,
        label=label_s,
        note=note_s,
    )
    _write_db_settings(
        _bootstrap_db_path(root),
        balance=bal,
        as_of=as_of_s,
        label=label_s,
        note=note_s,
    )
    return payload


def _balances_disagree(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) > 0.005
    except (TypeError, ValueError):
        return True


def _note_missing_balance(note: Optional[str], balance: Any) -> bool:
    if note is None or str(note).strip() == "":
        return True
    try:
        bal_norm = _normalize_amount_text(_format_balance(float(balance)))
    except (TypeError, ValueError):
        return True
    note_norm = _normalize_amount_text(note)
    return bal_norm not in note_norm


def check_live_checking_consistency(root: Optional[Path | str] = None) -> list[str]:
    """Return human-readable issues if JSON vs DBs disagree or notes are stale."""
    issues: list[str] = []
    json_path = _json_path(root)
    cash_path = _cashflow_db_path(root)
    boot_path = _bootstrap_db_path(root)

    if not json_path.exists():
        issues.append(f"missing live checking JSON: {json_path}")
        return issues

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"unreadable live checking JSON: {exc}")
        return issues

    if not isinstance(raw, dict):
        issues.append("live checking JSON is not an object")
        return issues

    json_bal = raw.get("balance")
    json_as_of = raw.get("as_of")
    json_note = raw.get("as_of_note")

    cash = _read_db_settings(cash_path)
    boot = _read_db_settings(boot_path)

    if not cash_path.exists():
        issues.append(f"missing cashflow DB: {cash_path}")
    if not boot_path.exists():
        issues.append(f"missing cloud_bootstrap DB: {boot_path}")

    for name, settings in (("cashflow.db", cash), ("cloud_bootstrap.db", boot)):
        db_bal = settings.get("live_checking_balance")
        db_as_of = settings.get("live_checking_as_of")
        db_note = settings.get("live_checking_note")

        if db_bal is None:
            issues.append(f"{name}: missing live_checking_balance")
        elif _balances_disagree(json_bal, db_bal):
            issues.append(
                f"{name}: balance {db_bal!r} != JSON balance {json_bal!r}"
            )

        if db_as_of is None:
            issues.append(f"{name}: missing live_checking_as_of")
        elif str(db_as_of) != str(json_as_of):
            issues.append(
                f"{name}: as_of {db_as_of!r} != JSON as_of {json_as_of!r}"
            )

        if _note_missing_balance(db_note, json_bal if json_bal is not None else db_bal):
            issues.append(
                f"{name}: live_checking_note does not contain balance amount"
            )

    if _note_missing_balance(json_note, json_bal):
        issues.append("live_checking.json as_of_note does not contain balance amount")

    return issues
