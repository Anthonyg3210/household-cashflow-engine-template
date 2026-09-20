"""Optional module flags (persisted settings) for the portable template.

Core always on: dashboard, monthly operating, insights, rules, month detail,
scenarios, import, settings, and forecast guard.

Optional (user-toggled): Debt Paydown, Net Worth, Retirement, Tax, Rewards.

Learning (due-date + variable amounts) turns on automatically when transaction
history is sufficient — never prompted at install.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import db

SETTING_MODULE_FLAGS = "module_flags"

OPTIONAL_MODULES: dict[str, dict[str, str]] = {
    "debt_paydown": {
        "label": "Debt Paydown",
        "nav": "Household debt paydown",
        "enable_nav": "Enable Debt Paydown",
    },
    "net_worth": {
        "label": "Net Worth",
        "nav": "",
        "enable_nav": "",
    },
    "retirement": {
        "label": "Retirement",
        "nav": "Retirement runway",
        "enable_nav": "Enable Retirement",
    },
    "tax": {
        "label": "Tax",
        "nav": "",
        "enable_nav": "",
    },
    "rewards": {
        "label": "Rewards",
        "nav": "Rewards Card — demo rewards card",
        "enable_nav": "Enable Rewards",
    },
}

CORE_ALWAYS_ON = (
    "dashboard",
    "monthly_operating",
    "insights",
    "rules",
    "month_detail",
    "scenarios",
    "import",
    "settings",
    "forecast_guard",
)

LEARNING_MIN_ACTUALS = 5
DUE_DATE_MIN_SAMPLES = 3

_ROOT = Path(__file__).resolve().parent.parent

_CLEAN_WIPE_SIDECARS = (
    _ROOT / "data" / "tax_profile.json",
    _ROOT / "data" / "retirement_plan.json",
    _ROOT / "data" / "retirement_snapshot.json",
    _ROOT / "data" / "net_worth_snapshot.json",
    _ROOT / "data" / "black_card_snapshot.json",
    _ROOT / "data" / "black_card_budget_context.json",
)


def default_flags(*, demo: bool = False) -> dict[str, bool]:
    on = bool(demo)
    return {key: on for key in OPTIONAL_MODULES}


def _coerce_flags(raw: Any, *, demo: bool = False) -> dict[str, bool]:
    base = default_flags(demo=demo)
    if not isinstance(raw, dict):
        return base
    for key in OPTIONAL_MODULES:
        if key in raw:
            base[key] = bool(raw[key])
    return base


def load_module_flags(conn, *, demo_default: Optional[bool] = None) -> dict[str, bool]:
    if demo_default is None:
        try:
            from .household_init import INIT_MODE_DEMO, get_init_mode

            demo_default = get_init_mode(conn) == INIT_MODE_DEMO
        except Exception:
            demo_default = False
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (SETTING_MODULE_FLAGS,)
    ).fetchone()
    if not row:
        return default_flags(demo=bool(demo_default))
    val = row["value"] if hasattr(row, "keys") else row[0]
    try:
        raw = json.loads(val) if isinstance(val, str) else val
    except (TypeError, json.JSONDecodeError):
        return default_flags(demo=bool(demo_default))
    return _coerce_flags(raw, demo=bool(demo_default))


def save_module_flags(conn, flags: dict[str, bool]) -> dict[str, bool]:
    cleaned = _coerce_flags(flags, demo=False)
    db.set_setting(conn, SETTING_MODULE_FLAGS, json.dumps(cleaned, sort_keys=True))
    return cleaned


def set_module_enabled(conn, module_id: str, enabled: bool) -> dict[str, bool]:
    if module_id not in OPTIONAL_MODULES:
        raise ValueError(f"Unknown module: {module_id}")
    flags = load_module_flags(conn)
    flags[module_id] = bool(enabled)
    return save_module_flags(conn, flags)


def is_module_enabled(conn, module_id: str) -> bool:
    return bool(load_module_flags(conn).get(module_id))


def wipe_optional_sidecars() -> list[str]:
    """Remove optional module sidecars (Clean init). Never creates them."""
    removed: list[str] = []
    for path in _CLEAN_WIPE_SIDECARS:
        try:
            if path.exists():
                path.unlink()
                removed.append(path.name)
        except OSError:
            pass
    return removed


def learning_status(conn) -> dict[str, Any]:
    actuals_n = int(
        conn.execute("SELECT COUNT(*) AS c FROM actuals").fetchone()["c"] or 0
    )
    due = "ready" if actuals_n >= DUE_DATE_MIN_SAMPLES else "waiting_for_history"
    variable = "ready" if actuals_n >= LEARNING_MIN_ACTUALS else "waiting_for_history"
    overall = "ready" if actuals_n >= LEARNING_MIN_ACTUALS else "waiting_for_history"
    return {
        "due_date": due,
        "variable_amounts": variable,
        "overall": overall,
        "actuals": actuals_n,
    }


def module_config_state(
    conn, module_id: str, flags: Optional[dict[str, bool]] = None
) -> str:
    """ready | not_enabled | waiting_for_history | needs_setup"""
    flags = flags if flags is not None else load_module_flags(conn)
    if not flags.get(module_id):
        return "not_enabled"

    if module_id == "debt_paydown":
        from .debt_paydown import DEBTS_PATH

        n = 0
        if DEBTS_PATH.exists():
            try:
                raw = json.loads(DEBTS_PATH.read_text(encoding="utf-8"))
                n = len(raw.get("debts") or [])
            except (OSError, json.JSONDecodeError):
                n = 0
        return "ready" if n > 0 else "needs_setup"

    if module_id == "net_worth":
        from .net_worth import SNAPSHOT_PATH, load_snapshot

        snap = load_snapshot(SNAPSHOT_PATH)
        if (
            snap.get("fidelity_brokerage_balance") is None
            and snap.get("savings_balance") is None
        ):
            return "needs_setup"
        return "ready"

    if module_id == "retirement":
        return (
            "ready"
            if (_ROOT / "data" / "retirement_plan.json").exists()
            else "needs_setup"
        )

    if module_id == "tax":
        return (
            "ready" if (_ROOT / "data" / "tax_profile.json").exists() else "needs_setup"
        )

    if module_id == "rewards":
        from .bank_import import BLACK_CARD_SOURCE

        n = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM actuals WHERE source = ?",
                (BLACK_CARD_SOURCE,),
            ).fetchone()["c"]
            or 0
        )
        return "ready" if n > 0 else "waiting_for_history"

    return "not_enabled"


def status_label(status: str) -> str:
    return {
        "ready": "Ready",
        "not_enabled": "Not enabled",
        "waiting_for_history": "Waiting for history",
        "needs_setup": "Needs setup",
    }.get(status, status)


def module_status_map(conn) -> dict[str, dict[str, Any]]:
    flags = load_module_flags(conn)
    out: dict[str, dict[str, Any]] = {}
    for mid, meta in OPTIONAL_MODULES.items():
        st = module_config_state(conn, mid, flags)
        out[mid] = {
            "id": mid,
            "label": meta["label"],
            "status": st,
            "status_label": status_label(st),
            "enabled": bool(flags.get(mid)),
        }
    learn = learning_status(conn)
    out["learning"] = {
        "id": "learning",
        "label": "Due-date / variable learning",
        "status": learn["overall"],
        "status_label": status_label(learn["overall"]),
        "enabled": True,
    }
    return out


def nav_pages_for_flags(flags: dict[str, bool]) -> list[str]:
    pages = [
        "Household Cashflow Engine Dashboard",
        "Household monthly operating income & expenses",
        "Household spending & income insights",
    ]
    meta = OPTIONAL_MODULES["rewards"]
    pages.append(meta["nav"] if flags.get("rewards") else meta["enable_nav"])
    meta = OPTIONAL_MODULES["debt_paydown"]
    pages.append(meta["nav"] if flags.get("debt_paydown") else meta["enable_nav"])
    meta = OPTIONAL_MODULES["retirement"]
    pages.append(meta["nav"] if flags.get("retirement") else meta["enable_nav"])
    pages.extend(
        [
            "Rules",
            "Month detail",
            "Scenarios",
            "Import",
            "Settings",
        ]
    )
    return pages
