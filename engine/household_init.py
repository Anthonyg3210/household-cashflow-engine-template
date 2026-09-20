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
    from .module_flags import default_flags, save_module_flags

    save_module_flags(conn, default_flags(demo=True))
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
    from .module_flags import default_flags, save_module_flags, wipe_optional_sidecars

    wipe_optional_sidecars()  # never leave demo tax/retirement/rewards/net-worth files
    save_module_flags(conn, default_flags(demo=False))

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
    """Core / modules / learning strip — Ready, Not enabled, Waiting for history."""
    from .module_flags import (
        learning_status,
        load_module_flags,
        module_status_map,
        status_label,
    )

    mode = get_init_mode(conn) or (
        INIT_MODE_DEMO if not db.is_empty(conn) else None
    )
    settings = db.get_settings(conn)
    rules_n = int(
        conn.execute("SELECT COUNT(*) AS c FROM recurring_rules").fetchone()["c"] or 0
    )
    actuals_n = int(
        conn.execute("SELECT COUNT(*) AS c FROM actuals").fetchone()["c"] or 0
    )
    core_ready = settings is not None and mode is not None

    flags = load_module_flags(conn)
    status_map = module_status_map(conn)
    learn = learning_status(conn)

    modules_ready = [
        m["label"] for m in status_map.values() if m["id"] != "learning" and m["status"] == "ready"
    ]
    modules_not_enabled = [
        m["label"]
        for m in status_map.values()
        if m["id"] != "learning" and m["status"] == "not_enabled"
    ]
    modules_waiting = [
        m["label"]
        for m in status_map.values()
        if m["id"] != "learning"
        and m["status"] in ("waiting_for_history", "needs_setup")
    ]

    if modules_ready and not modules_not_enabled and not modules_waiting:
        label_modules = "Modules: " + ", ".join(modules_ready)
    elif not modules_ready and modules_not_enabled and not modules_waiting:
        label_modules = "Modules not enabled"
    else:
        parts = []
        if modules_ready:
            parts.append("Ready: " + ", ".join(modules_ready))
        if modules_not_enabled:
            parts.append("Not enabled: " + ", ".join(modules_not_enabled))
        if modules_waiting:
            parts.append("Waiting: " + ", ".join(modules_waiting))
        label_modules = " · ".join(parts) if parts else "Modules not enabled"

    return {
        "mode": mode,
        "core": "ready" if core_ready else "needs_init",
        "rules": rules_n,
        "actuals": actuals_n,
        "flags": flags,
        "module_status": status_map,
        "modules_ready": modules_ready,
        "modules_not_enabled": modules_not_enabled,
        "modules_waiting": modules_waiting,
        "learning": learn["overall"],
        "label_core": "Core ready" if core_ready else "Core needs setup",
        "label_modules": label_modules,
        "label_learning": (
            "Learning waiting for history"
            if learn["overall"] == "waiting_for_history"
            else "Learning ready"
        ),
    }


