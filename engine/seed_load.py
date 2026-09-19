"""Import local seed/ (preferred) into SQLite.

Policy choices (documented in README / data/excel_parity_oct_plus.md):
- Live seam after import: start_balance 5000.00 on 2026-09-12 + Sep Budget workbook override
  (if data/family_budget_sep2026_forecast.json is present).
- Default rule set is **Excel-parity** (double mortgage FY24-27, partner allowance −2500 through
  Feb 2027, side_gig Other Income stamps, HOA/presser/bonus overlays).
- Jordan 2028 blank in Excel → default **0** (excel_blank). inherit_2027 is opt-in.
- prefer_single_mortgage=True skips FY24-27 day-10 −2450.00 (cleaned what-if).
- Paychecks: Alex biweekly (anchor 2026-09-11); Jordan monthly day 8.
- Re-import does **not** wipe bank_csv actuals.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from . import db

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"  # template: local synthetic only
LOCAL_SEED = Path(__file__).resolve().parent.parent / "seed"


def _load_json(path: Path):
    return json.loads(path.read_text())


def resolve_seed_dir() -> Optional[Path]:
    """Template uses only the in-repo synthetic seed/ (never external paths)."""
    if (LOCAL_SEED / "rules.json").exists():
        return LOCAL_SEED
    return None



def import_seed(
    conn,
    seed_dir: Optional[Path] = None,
    *,
    prefer_single_mortgage: bool = False,
    secondary_2028_inherit: bool = False,
    reset: bool = True,
) -> dict:
    """Load seed into DB. Returns import summary."""
    seed_dir = seed_dir or resolve_seed_dir()
    if seed_dir is None:
        raise FileNotFoundError("No seed directory found")

    # Copy into project seed/ for portability (skip when already using LOCAL_SEED —
    # Streamlit Cloud has no local seed/, so seed_dir IS local seed).
    LOCAL_SEED.mkdir(parents=True, exist_ok=True)
    try:
        same_seed = seed_dir.resolve() == LOCAL_SEED.resolve()
    except OSError:
        same_seed = False
    if not same_seed:
        for f in seed_dir.glob("*.json"):
            dest = LOCAL_SEED / f.name
            if dest.resolve() != f.resolve():
                shutil.copy2(f, dest)
        readme = seed_dir / "README.md"
        if readme.exists():
            dest_r = LOCAL_SEED / "README.md"
            if dest_r.resolve() != readme.resolve():
                shutil.copy2(readme, dest_r)

    rules_raw = _load_json(seed_dir / "rules.json")
    paychecks = _load_json(seed_dir / "paychecks.json")
    starting = _load_json(seed_dir / "starting_balance.json")
    categories = None
    if (seed_dir / "categories.json").exists():
        categories = _load_json(seed_dir / "categories.json")

    if reset:
        conn.executescript(
            """
            DELETE FROM recurring_rules;
            DELETE FROM planned_items;
            DELETE FROM scenarios;
            DELETE FROM settings;
            """
        )
        conn.commit()

    preferred = starting["preferredSeed"]
    rocket = starting.get("mortgagePayment", {}).get("amount", 950.00)

    # Settings: start day after preferred seed date
    start_date = "2026-09-01"  # forecast seam
    # Keep 3y-ish horizon ending 2029-09-12 per product brief
    end_date = "2029-09-12"
    db.save_settings(
        conn,
        {
            "start_date": start_date,
            "end_date": end_date,
            "start_balance": float(preferred["amount"]),
            "warning_threshold": 100.0,
            "breach_threshold": 0.0,
        },
    )
    # Store metadata
    db.set_setting(conn, "seed_source", str(seed_dir))
    db.set_setting(conn, "seed_balance_date", preferred["date"])
    db.set_setting(conn, "rocket_loans_x11", str(rocket))
    db.set_setting(conn, "secondary_2028_policy", "inherit_2027" if secondary_2028_inherit else "zero")
    db.set_setting(conn, "mortgage_policy", "single_loans_x11" if prefer_single_mortgage else "excel_double")

    # --- Recurring expense rules with block date windows ---
    imported_rules = 0
    skipped_double_mortgage = 0
    for r in rules_raw:
        block = r.get("block") or "fy24_27"
        cat = r["category"]
        dom = int(r["dayOfMonth"])
        amt = float(r["amount"])

        if block == "fy24_27":
            r_start, r_end = "2026-09-01", "2027-12-31"
        elif block == "fy2028":
            r_start, r_end = "2028-01-01", "2029-12-31"  # extend 2028 template through horizon
        else:
            r_start, r_end = None, None

        # Preferred: single Mortgage from Loans for fy24_27
        if prefer_single_mortgage and cat == "Home Mortgage" and block == "fy24_27":
            if dom == 10 and abs(amt) > 2000:
                # Skip the large day-10 duplicate
                skipped_double_mortgage += 1
                continue
            if dom == 11:
                amt = -abs(float(rocket))  # ensure Loans!X11 magnitude

        db.upsert_rule(
            conn,
            {
                "category": cat,
                "label": cat,
                "day_of_month": dom,
                "amount": amt,
                "amount_by_year": {},
                "cadence": "monthly_dom",
                "start_date": r_start,
                "end_date": r_end,
                "enabled": True,
            },
        )
        imported_rules += 1

    # --- Paychecks ---
    alex = {int(k): float(v) for k, v in paychecks["alex"].items() if v is not None}
    # Extend 2029+ with last known
    last_a = alex[max(alex)]
    for y in range(2029, 2031):
        alex.setdefault(y, last_a)

    jordan_raw = paychecks["jordan"]
    jordan = {}
    for k, v in jordan_raw.items():
        y = int(k)
        if v is None:
            if secondary_2028_inherit:
                # inherit prior year
                prior = jordan.get(y - 1) or jordan_raw.get(str(y - 1)) or jordan_raw.get(y - 1)
                jordan[y] = float(prior) if prior is not None else 0.0
            else:
                jordan[y] = 0.0
        else:
            jordan[y] = float(v)
    last_d = jordan[max(jordan)] if jordan else 0.0
    for y in range(2029, 2031):
        jordan.setdefault(y, last_d)

    db.upsert_rule(
        conn,
        {
            "category": "Alex's Income",
            "label": "Alex paycheck (biweekly)",
            "day_of_month": None,
            "amount": alex.get(2026, 4200.00),
            "amount_by_year": alex,
            "cadence": "biweekly",
            "anchor_date": "2026-09-11",  # Friday payday pattern from Excel
            "interval_days": 14,
            "start_date": "2026-09-01",
            "end_date": None,
            "enabled": True,
        },
    )
    imported_rules += 1

    db.upsert_rule(
        conn,
        {
            "category": "Jordan's Income",
            "label": "Jordan income (monthly)",
            "day_of_month": 8,
            "amount": jordan.get(2026, 1500.0),
            "amount_by_year": jordan,
            "cadence": "monthly_dom",
            "start_date": "2026-09-01",
            "end_date": None,
            "enabled": True,
        },
    )
    imported_rules += 1

    # Seed example scenarios for the sandbox
    _seed_example_scenarios(conn)

    if categories:
        db.set_setting(conn, "categories_json", json.dumps(categories.get("categories", categories)))

    from .excel_parity import apply_excel_parity

    parity = apply_excel_parity(
        conn,
        prefer_single_mortgage=prefer_single_mortgage,
        secondary_2028_inherit=secondary_2028_inherit,
    )
    seam = _restore_live_seam(conn)

    summary = {
        "seed_dir": str(seed_dir),
        "rules_imported": imported_rules,
        "skipped_double_mortgage": skipped_double_mortgage,
        "start_balance": seam.get("start_balance", float(preferred["amount"])),
        "start_date": seam.get("start_date", start_date),
        "end_date": end_date,
        "jordan_2028": 1500.0 if secondary_2028_inherit else 0.0,
        "mortgage_policy": "single_loans_x11" if prefer_single_mortgage else "excel_double",
        "prefer_single_mortgage": prefer_single_mortgage,
        "excel_parity": parity,
        "live_seam": seam,
    }
    db.set_setting(conn, "import_summary", json.dumps(summary, default=str))
    return summary


SEP_FORECAST = Path(__file__).resolve().parent.parent / "data" / "family_budget_sep2026_forecast.json"
SEP_SOURCE = "family_budget_sep2026_forecast"


def _restore_live_seam(conn) -> dict:
    """Reload Sep Budget workbook planned + live start_balance / suppress if JSON exists."""
    if not SEP_FORECAST.exists():
        return {"restored": False}
    payload = json.loads(SEP_FORECAST.read_text())
    items = payload.get("items") or []
    db.clear_planned_by_source(conn, payload.get("source") or SEP_SOURCE)
    for it in items:
        db.add_planned(
            conn,
            {
                "date": it["date"],
                "amount": it["amount"],
                "category": it["category"],
                "label": it.get("label")
                or f"Budget workbook {it['date']} · {it['category']} (source={SEP_SOURCE})",
                "source": payload.get("source") or SEP_SOURCE,
                "enabled": True,
            },
        )
    start_date = payload.get("start_date", "2026-09-12")
    start_balance = payload.get("start_balance", 5000.00)
    suppress = payload.get("suppress_rules_through", "2026-09-30")
    db.set_setting(conn, "start_date", start_date)
    db.set_setting(conn, "start_balance", str(start_balance))
    db.set_setting(conn, "suppress_rules_through", suppress)
    db.set_setting(conn, "end_date", "2029-09-12")
    return {
        "restored": True,
        "planned": len(items),
        "start_date": start_date,
        "start_balance": float(start_balance),
        "suppress_rules_through": suppress,
    }


def _seed_example_scenarios(conn) -> None:
    """Create a couple of starter scenarios illustrating the sandbox."""
    examples = [
        {
            "name": "Bonus kept as cash (2026)",
            "description": (
                "$8,000 bonus on 2026-12-15 stays in checking (not spent on debt). "
                "Compare vs Baseline and vs 'Bonus → debt payoff'."
            ),
            "deltas": [
                {
                    "kind": "one_off",
                    "label": "Annual bonus",
                    "category": "Other Income",
                    "amount": 8000.0,
                    "on_date": "2026-12-15",
                    "mode": "add",
                },
            ],
        },
        {
            "name": "Bonus → debt payoff (2026)",
            "description": (
                "Same $8,000 bonus on 2026-12-15 immediately redirected to Debt Payoff "
                "(checking impact nets to ~Baseline; models 'don't spend the bonus')."
            ),
            "deltas": [
                {
                    "kind": "one_off",
                    "label": "Annual bonus",
                    "category": "Other Income",
                    "amount": 8000.0,
                    "on_date": "2026-12-15",
                    "mode": "add",
                },
                {
                    "kind": "redirect",
                    "label": "Apply bonus to debt",
                    "redirect_from_category": "Other Income",
                    "redirect_to_category": "Debt Payoff",
                    "on_date": "2026-12-15",
                    "redirect_amount": 8000.0,
                },
            ],
        },
        {
            "name": "Cut Savings transfer 50%",
            "description": "Halve the monthly Savings outflow (−3500 → −1750) from 2026-09 onward; see min-EOD / breach impact.",
            "deltas": [
                {
                    "kind": "expense_change",
                    "label": "Savings −50%",
                    "category": "Savings",
                    "mode": "pct",
                    "amount": -50.0,
                    "start_date": "2026-09-01",
                }
            ],
        },
        {
            "name": "Raise Jordan +$500/mo",
            "description": "Increase Jordan's Income by $500 each month occurrence.",
            "deltas": [
                {
                    "kind": "income_change",
                    "label": "Jordan +500",
                    "category": "Jordan's Income",
                    "mode": "add",
                    "amount": 500.0,
                    "start_date": "2026-09-01",
                }
            ],
        },
    ]
    for sc in examples:
        db.save_scenario(conn, sc)


def _parity_flags_from_settings(conn) -> tuple[bool, bool]:
    """Read rocket / Jordan 2028 policies already stored on the live DB."""
    rows = {
        r["key"]: r["value"]
        for r in conn.execute(
            "SELECT key, value FROM settings WHERE key IN ('mortgage_policy','secondary_2028_policy')"
        ).fetchall()
    }
    prefer_single_mortgage = rows.get("mortgage_policy") == "single_loans_x11"
    secondary_2028_inherit = rows.get("secondary_2028_policy") == "inherit_2027"
    return prefer_single_mortgage, secondary_2028_inherit


def ensure_seeded(conn) -> dict:
    """Init schema, import seed if empty, then always re-apply excel parity.

    Streamlit Cloud keeps a persistent cashflow.db across deploys. Bootstrap
    restore only replaces *thin* DBs, so new recurring overlays (e.g. Demo Cleaners
    cleaning) shipped in code would never land unless we upsert them on every
    boot. ``apply_excel_parity`` is surgical: it upserts labeled rules and
    refreshes ``excel_parity_forecast`` planned rows without wiping Chase
    actuals or Sep Budget workbook planned.
    """
    db.init_db(conn)
    if db.is_empty(conn):
        if resolve_seed_dir():
            # import_seed already calls apply_excel_parity
            return import_seed(conn)
        # Minimal fallback if no seed files
        db.save_settings(
            conn,
            {
                "start_date": "2026-09-01",
                "end_date": "2029-09-12",
                "start_balance": 2500.00,
                "warning_threshold": 100.0,
                "breach_threshold": 0.0,
            },
        )
        summary = {"seed_dir": None, "rules_imported": 0, "fallback": True}
    else:
        summary = {"already_seeded": True}

    from .excel_parity import apply_excel_parity

    prefer_single_mortgage, secondary_2028_inherit = _parity_flags_from_settings(conn)
    summary["excel_parity"] = apply_excel_parity(
        conn,
        prefer_single_mortgage=prefer_single_mortgage,
        secondary_2028_inherit=secondary_2028_inherit,
    )
    return summary
