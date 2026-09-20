"""Household init modes: Explore Demo vs Start My Household (clean).

Demo keeps the intentional Alex/Jordan synthetic household.
Clean is portable: generic settings only — no demo rules, paychecks,
debts, scenarios, excel-parity overlays, or module seed files.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import db

INIT_MODE_DEMO = "demo"
INIT_MODE_CLEAN = "clean"
SETTING_INIT_MODE = "household_init_mode"
SETTING_HOUSEHOLD_NAME = "household_name"

_ROOT = Path(__file__).resolve().parent.parent
_SYNTHETIC_DEBTS = _ROOT / "sample" / "fixtures" / "synthetic" / "debts.json"
_DEMO_BOOTSTRAP = _ROOT / "sample" / "demo_bootstrap.db"


def empty_debts_store() -> dict[str, Any]:
    return {
        "as_of": None,
        "cashflow_link_note": "",
        "default_scenario": None,
        "debts": [],
    }


def peek_setting(db_path: Path, key: str) -> Optional[str]:
    """Read one settings value without opening the app connection."""
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return str(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def peek_init_mode(db_path: Optional[Path] = None) -> Optional[str]:
    path = Path(db_path) if db_path else db.DB_PATH
    mode = peek_setting(path, SETTING_INIT_MODE)
    if mode in (INIT_MODE_DEMO, INIT_MODE_CLEAN):
        return mode
    return None


def get_init_mode(conn) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (SETTING_INIT_MODE,)
    ).fetchone()
    if not row:
        return None
    val = row["value"] if isinstance(row, sqlite3.Row) else row[0]
    if val in (INIT_MODE_DEMO, INIT_MODE_CLEAN):
        return str(val)
    return None


def set_init_mode(conn, mode: str) -> None:
    if mode not in (INIT_MODE_DEMO, INIT_MODE_CLEAN):
        raise ValueError(f"Unknown init mode: {mode}")
    db.set_setting(conn, SETTING_INIT_MODE, mode)


def count_rules(db_path: Path) -> int:
    path = Path(db_path)
    if not path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(path))
        try:
            n = conn.execute("SELECT COUNT(*) FROM recurring_rules").fetchone()[0]
            return int(n or 0)
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def needs_first_run(db_path: Optional[Path] = None) -> bool:
    """True when the user has not chosen Demo vs Clean yet."""
    path = Path(db_path) if db_path else db.DB_PATH
    mode = peek_init_mode(path)
    if mode is not None:
        return False
    # Legacy: already has synthetic rules but no mode flag → treat as demo later.
    if path.exists() and count_rules(path) > 0:
        return False
    return True


def _write_debts_file(store: dict[str, Any]) -> None:
    from .debt_paydown import DEBTS_PATH, save_debts

    save_debts(store, path=DEBTS_PATH)


def _install_demo_debts() -> None:
    from .debt_paydown import DEBTS_PATH, default_seed, save_debts

    if _SYNTHETIC_DEBTS.exists():
        DEBTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SYNTHETIC_DEBTS, DEBTS_PATH)
    else:
        save_debts(default_seed(), path=DEBTS_PATH)


def init_demo_household(
    conn,
    *,
    prefer_single_mortgage: bool = False,
    secondary_2028_inherit: bool = False,
) -> dict[str, Any]:
    """Load synthetic Alex/Jordan seed + excel parity + demo debts."""
    from .seed_load import import_seed, resolve_seed_dir

    db.init_db(conn)
    seed_dir = resolve_seed_dir()
    if seed_dir is None:
        raise FileNotFoundError("No synthetic seed/ directory found for Explore Demo")
    summary = import_seed(
        conn,
        seed_dir,
        prefer_single_mortgage=prefer_single_mortgage,
        secondary_2028_inherit=secondary_2028_inherit,
        reset=True,
    )
    set_init_mode(conn, INIT_MODE_DEMO)
    db.set_setting(conn, SETTING_HOUSEHOLD_NAME, "Alex & Jordan (demo)")
    _install_demo_debts()
    summary[SETTING_INIT_MODE] = INIT_MODE_DEMO
    return summary


def init_clean_household(
    conn,
    *,
    household_name: str = "",
    start_date: str | date = None,
    end_date: str | date = None,
    start_balance: float = 0.0,
    warning_threshold: float = 100.0,
    as_of: str = "",
    breach_threshold: float = 0.0,
) -> dict[str, Any]:
    """Portable blank household — no demo finances of any kind."""
    db.init_db(conn)
    today = date.today()
    if start_date is None:
        start_date = today.isoformat()
    if end_date is None:
        end_date = date(today.year + 3, today.month, today.day).isoformat()
    if isinstance(start_date, date):
        start_date = start_date.isoformat()
    if isinstance(end_date, date):
        end_date = end_date.isoformat()

    # Wipe any prior demo residue (rules/planned/scenarios/settings/actuals).
    conn.executescript(
        """
        DELETE FROM recurring_rules;
        DELETE FROM planned_items;
        DELETE FROM scenarios;
        DELETE FROM actuals;
        DELETE FROM settings;
        """
    )
    conn.commit()

    db.save_settings(
        conn,
        {
            "start_date": start_date,
            "end_date": end_date,
            "start_balance": float(start_balance),
            "warning_threshold": float(warning_threshold),
            "breach_threshold": float(breach_threshold),
            "suppress_rules_through": "",
        },
    )
    set_init_mode(conn, INIT_MODE_CLEAN)
    name = (household_name or "").strip()
    db.set_setting(conn, SETTING_HOUSEHOLD_NAME, name)
    if (as_of or "").strip():
        db.set_setting(conn, "balances_as_of", as_of.strip())
    db.set_setting(conn, "seed_source", "clean_household")
    _write_debts_file(empty_debts_store())

    return {
        SETTING_INIT_MODE: INIT_MODE_CLEAN,
        "household_name": name,
        "start_date": start_date,
        "end_date": end_date,
        "start_balance": float(start_balance),
        "warning_threshold": float(warning_threshold),
        "as_of": (as_of or "").strip() or None,
        "rules_imported": 0,
        "excel_parity": None,
    }


def capability_status(conn) -> dict[str, Any]:
    """Lightweight readiness for the status strip (not a feature matrix)."""
    mode = get_init_mode(conn) or (
        INIT_MODE_DEMO if not db.is_empty(conn) else None
    )
    settings = db.get_settings(conn)
    rules_n = conn.execute("SELECT COUNT(*) AS c FROM recurring_rules").fetchone()["c"]
    actuals_n = conn.execute("SELECT COUNT(*) AS c FROM actuals").fetchone()["c"]

    from .debt_paydown import DEBTS_PATH

    debts_n = 0
    if DEBTS_PATH.exists():
        try:
            raw = json.loads(DEBTS_PATH.read_text(encoding="utf-8"))
            debts_n = len(raw.get("debts") or [])
        except (OSError, json.JSONDecodeError):
            debts_n = 0

    tax_on = (_ROOT / "data" / "tax_profile.json").exists()
    retirement_on = (_ROOT / "data" / "retirement_plan.json").exists()
    rewards_on = actuals_n > 0 and mode == INIT_MODE_DEMO

    core_ready = settings is not None and mode is not None
    modules_enabled = []
    modules_waiting = []
    if debts_n > 0:
        modules_enabled.append("debt")
    else:
        modules_waiting.append("debt")
    if tax_on:
        modules_enabled.append("tax")
    else:
        modules_waiting.append("tax")
    if retirement_on:
        modules_enabled.append("retirement")
    else:
        modules_waiting.append("retirement")
    if rewards_on or mode == INIT_MODE_DEMO:
        if mode == INIT_MODE_DEMO:
            modules_enabled.append("rewards")
        else:
            modules_waiting.append("rewards")
    else:
        modules_waiting.append("rewards")

    learning = "ready" if actuals_n >= 5 else "waiting"

    return {
        "mode": mode,
        "core": "ready" if core_ready else "needs_init",
        "rules": int(rules_n),
        "actuals": int(actuals_n),
        "modules_enabled": modules_enabled,
        "modules_waiting": modules_waiting,
        "learning": learning,
        "label_core": "Core ready" if core_ready else "Core needs setup",
        "label_modules": (
            "Modules not enabled"
            if modules_waiting and not modules_enabled
            else (
                f"Modules: {', '.join(modules_enabled)}"
                + (f" · waiting: {', '.join(modules_waiting)}" if modules_waiting else "")
                if modules_enabled
                else "Modules not enabled"
            )
        ),
        "label_learning": (
            "Learning waiting for transactions"
            if learning == "waiting"
            else "Learning has transaction signal"
        ),
    }
