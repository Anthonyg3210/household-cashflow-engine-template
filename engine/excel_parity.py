"""Excel-parity rule overlays for Oct 2026+ Budget workbook month-ends.

Data Input VLOOKUP is the backbone, but Budget workbook still hard-stamps
income, partner allowance (−2500 through Feb 2027), side_gig $550, HOA,
pressure-cleaning, and the Mar-2027 $24k other-income. This module applies
those overlays so twin month_end matches Summary Dashboard / row 90.

Does not modify the original Excel workbook.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from . import db

PLANNED_SOURCE = "excel_parity_forecast"

LABEL_MORTGAGE_D10 = "Home Mortgage (Excel FY24-27 day 10)"
LABEL_WIFE_2500 = "Partner Allowance (Excel -2500 through 2027-02)"
LABEL_WIFE_3500 = "Partner Allowance (Data Input -3500 from 2027-03)"
LABEL_SIDE_GIG = "Other Income (Excel side-gig / budget stamps stamps)"
LABEL_OLD_SIDE_GIG = "Jordan side gig (biweekly, 2026 only)"
LABEL_DEMO_CLEANING = "Demo Cleaners service ($180/mo)"
SCENARIO_CLEANED_MORTGAGE = "Cleaned single-mortgage (what-if)"

# Cached Summary Dashboard col C / Budget workbook row-90 month totals
EXCEL_MONTH_ENDS = {
    (2026, 9): 2200.00,
    (2026, 10): 1900.00,
    (2026, 11): 1600.00,
    (2026, 12): -400.00,
    (2027, 1): 3500.00,
    (2027, 2): 3200.00,
    (2027, 3): 24000.00,
    (2027, 4): 21500.00,
    (2027, 5): 19000.00,
    (2027, 6): 16500.00,
    (2027, 7): 18000.00,
    (2027, 8): 15500.00,
    (2027, 9): 13000.00,
    (2027, 10): 10500.00,
    (2027, 11): 8000.00,
    (2027, 12): 9000.00,
    (2028, 1): 9500.00,
    (2028, 2): 10000.00,
    (2028, 3): 10800.00,
    (2028, 4): 11500.00,
    (2028, 5): 12000.00,
    (2028, 6): 17000.00,
    (2028, 7): 17500.00,
    (2028, 8): 18000.00,
    (2028, 9): 18800.00,
    (2028, 10): 19500.00,
    (2028, 11): 20000.00,
    (2028, 12): 24000.00,
}


def extra_rules(*, include_day10_mortgage: bool = True) -> list[dict]:
    """Recurring overlays (not in sparse Data Input day-grid as modeled)."""
    rules = []
    if include_day10_mortgage:
        rules.append(
            {
                "category": "Home Mortgage",
                "label": LABEL_MORTGAGE_D10,
                "day_of_month": 10,
                "amount": -2450.00,
                "cadence": "monthly_dom",
                "start_date": "2026-10-01",
                "end_date": "2027-12-31",
                "enabled": True,
            }
        )
    rules.extend(
        [
            {
                "category": "Partner Allowance",
                "label": LABEL_WIFE_2500,
                "day_of_month": 28,
                "amount": -2500.0,
                "cadence": "monthly_dom",
                "start_date": "2026-10-01",
                "end_date": "2027-02-28",
                "enabled": True,
            },
            {
                "category": "Partner Allowance",
                "label": LABEL_WIFE_3500,
                "day_of_month": 28,
                "amount": -3500.0,
                "cadence": "monthly_dom",
                "start_date": "2027-03-01",
                "end_date": "2027-12-31",
                "enabled": True,
            },
            {
                # Opposite Alex biweekly Fridays (his anchor 2026-09-11).
                # Include Oct 2 so streak is complete after Sep Budget workbook stamps.
                "category": "Other Income",
                "label": LABEL_SIDE_GIG,
                "day_of_month": None,
                "amount": 550.0,
                "amount_by_year": {2026: 550.0, 2027: 550.0},
                "cadence": "biweekly",
                "anchor_date": "2026-10-02",
                "interval_days": 14,
                "start_date": "2026-10-02",
                "end_date": "2027-02-19",
                "enabled": True,
            },
        ]
    )
    return rules


def extra_planned() -> list[dict]:
    """Budget workbook hardcoded / annual-column stamps (not day-grid VLOOKUP)."""
    rows = [
        # Quarterly pressure cleaning (Data Input!AL65 = -150), Excel placement dates
        ("2026-11-20", -150.0, "Home Pressure Cleaning"),
        ("2027-02-20", -150.0, "Home Pressure Cleaning"),
        ("2027-05-20", -150.0, "Home Pressure Cleaning"),
        ("2027-08-20", -150.0, "Home Pressure Cleaning"),
        ("2027-11-20", -150.0, "Home Pressure Cleaning"),
        ("2028-02-20", -150.0, "Home Pressure Cleaning"),
        ("2028-05-19", -150.0, "Home Pressure Cleaning"),
        ("2028-08-20", -150.0, "Home Pressure Cleaning"),
        ("2028-11-20", -150.0, "Home Pressure Cleaning"),
        # Annual HOA (Data Input!AL6/AL7/AL8) — Dec placements + Jul 1 -$250
        ("2026-12-25", -268.45, "Homeowners Association Fee 1st"),
        ("2026-12-25", -268.45, "Homeowners Association Fee 2dn"),
        ("2026-12-25", -702.67, "Homeowners Addison Vill Dues"),
        ("2027-07-01", -250.0, "Homeowners Association Fee 1st"),
        ("2027-12-24", -268.45, "Homeowners Association Fee 1st"),
        ("2027-12-24", -268.45, "Homeowners Association Fee 2dn"),
        ("2027-12-24", -702.67, "Homeowners Addison Vill Dues"),
        ("2028-07-01", -250.0, "Homeowners Association Fee 1st"),
        ("2028-12-26", -268.45, "Homeowners Association Fee 1st"),
        ("2028-12-26", -268.45, "Homeowners Association Fee 2dn"),
        ("2028-12-26", -702.67, "Homeowners Addison Vill Dues"),
        # Budget workbook Other Income hardcoded
        ("2027-03-11", 24000.0, "Other Income"),
    ]
    out = []
    for d, amt, cat in rows:
        out.append(
            {
                "date": d,
                "amount": amt,
                "category": cat,
                "label": f"Excel Budget workbook {d} · {cat} (source={PLANNED_SOURCE})",
                "source": PLANNED_SOURCE,
                "enabled": True,
            }
        )
    return out


def _upsert_by_label(conn, rule: dict) -> int:
    label = rule["label"]
    existing = [r for r in db.list_rules(conn) if r.get("label") == label]
    # Side gig label may have a trailing note from a prior edit — still one rule.
    if not existing and label == LABEL_SIDE_GIG:
        existing = [
            r
            for r in db.list_rules(conn)
            if (r.get("label") or "").startswith(LABEL_SIDE_GIG)
        ]
    payload = dict(rule)
    if existing:
        payload["id"] = existing[0]["id"]
    return db.upsert_rule(conn, payload)


def _disable_matching(conn, pred) -> int:
    n = 0
    for r in db.list_rules(conn):
        if pred(r) and r.get("enabled", True):
            rr = dict(r)
            rr["enabled"] = False
            db.upsert_rule(conn, rr)
            n += 1
    return n


def apply_excel_parity(
    conn,
    *,
    prefer_single_mortgage: bool = False,
    secondary_2028_inherit: bool = False,
) -> dict:
    """Surgically align live rules/planned to Excel Oct+ month-ends.

    Preserves bank_csv actuals, Sep Budget workbook planned, scenarios (except
    refreshing the cleaned-mortgage what-if), and start_balance / start_date /
    suppress_rules_through.
    """
    # --- Mortgage day 10 ---
    rocket_d10 = None
    for r in db.list_rules(conn):
        if (
            r.get("category") == "Home Mortgage"
            and int(r.get("day_of_month") or 0) == 10
            and abs(float(r.get("amount") or 0)) > 2000
            and (r.get("start_date") or "") < "2028-01-01"
        ):
            rocket_d10 = r
            break

    if prefer_single_mortgage:
        if rocket_d10 and rocket_d10.get("enabled", True):
            rr = dict(rocket_d10)
            rr["enabled"] = False
            db.upsert_rule(conn, rr)
        mortgage_id = rocket_d10["id"] if rocket_d10 else None
    else:
        if rocket_d10:
            rr = dict(rocket_d10)
            rr["label"] = LABEL_MORTGAGE_D10
            rr["enabled"] = True
            rr["end_date"] = "2027-12-31"
            mortgage_id = db.upsert_rule(conn, rr)
        else:
            mortgage_id = _upsert_by_label(conn, extra_rules(include_day10_mortgage=True)[0])

    # --- Disable leftover unsplit wife (−3500 for all FY24-27) ---
    overlay_labels = {LABEL_WIFE_2500, LABEL_WIFE_3500, LABEL_MORTGAGE_D10, LABEL_SIDE_GIG}
    _disable_matching(
        conn,
        lambda r: (
            r.get("category") == "Partner Allowance"
            and r.get("label") not in overlay_labels
            and (r.get("start_date") or "") < "2028-01-01"
            and r.get("day_of_month") == 28
        ),
    )

    # --- Disable old Jordan-categorized side_gig ---
    _disable_matching(
        conn,
        lambda r: (
            "side_gig" in (r.get("label") or "").lower()
            and r.get("label") != LABEL_SIDE_GIG
        ),
    )

    # --- Demo Cleaners $180/mo (Home Cleaning) through budget horizon ---
    # Excel FY24–27 Data Input omits cleaning; real Chase pays Demo Cleaners ~$180 most months.
    # Sep 2026 already paid — forecast from Oct 2026 through end of twin (2029)
    # until Alex says otherwise. One continuous rule (not split FY28 day-20).
    # Note: Excel month-end targets then diverge by −$180/mo vs workbook.
    adi_all = [
        r
        for r in db.list_rules(conn)
        if r.get("category") == "Home Cleaning"
        or (r.get("label") or "").startswith(LABEL_DEMO_CLEANING)
    ]
    horizon_end = (db.get_settings(conn).get("end_date") or date(2029, 9, 12)).isoformat()
    adi_payload = {
        "category": "Home Cleaning",
        "label": LABEL_DEMO_CLEANING,
        "day_of_month": 15,
        "amount": -180.0,
        "amount_by_year": {},
        "cadence": "monthly_dom",
        "start_date": "2026-10-01",
        "end_date": horizon_end,
        "enabled": True,
    }
    if adi_all:
        primary = next(
            (r for r in adi_all if (r.get("label") or "").startswith(LABEL_DEMO_CLEANING)),
            adi_all[0],
        )
        adi_payload["id"] = primary["id"]
        db.upsert_rule(conn, adi_payload)
        for r in adi_all:
            if r["id"] != primary["id"] and r.get("enabled", True):
                rr = dict(r)
                rr["enabled"] = False
                db.upsert_rule(conn, rr)
    else:
        db.upsert_rule(conn, adi_payload)

    # --- Overlay rules ---
    for rule in extra_rules(include_day10_mortgage=False):
        _upsert_by_label(conn, rule)

    # --- Jordan 2028 ---
    for r in db.list_rules(conn):
        if r.get("category") == "Jordan's Income" and (r.get("cadence") or "") == "monthly_dom":
            aby = dict(r.get("amount_by_year") or {})
            # normalize keys to str
            aby = {str(k): v for k, v in aby.items()}
            if secondary_2028_inherit:
                prior = aby.get("2027") or r.get("amount") or 1500.0
                aby["2028"] = float(prior)
            else:
                aby["2028"] = 0.0
            rr = dict(r)
            rr["amount_by_year"] = aby
            db.upsert_rule(conn, rr)

    # --- Planned overlays (replace this source only) ---
    cleared = db.clear_planned_by_source(conn, PLANNED_SOURCE)
    planned = extra_planned()
    for it in planned:
        db.add_planned(conn, it)

    db.set_setting(
        conn, "mortgage_policy", "single_loans_x11" if prefer_single_mortgage else "excel_double"
    )
    db.set_setting(
        conn,
        "secondary_2028_policy",
        "inherit_2027" if secondary_2028_inherit else "excel_blank",
    )
    db.set_setting(conn, "excel_parity_applied", date.today().isoformat())

    # --- Cleaned single-mortgage scenario (what-if; not baseline) ---
    mortgage_id = mortgage_id or next(
        (
            r["id"]
            for r in db.list_rules(conn)
            if r.get("label") == LABEL_MORTGAGE_D10
        ),
        None,
    )
    _upsert_cleaned_mortgage_scenario(conn, mortgage_id)

    return {
        "mortgage_day10_id": mortgage_id,
        "mortgage_policy": "single_loans_x11" if prefer_single_mortgage else "excel_double",
        "secondary_2028_policy": "inherit_2027" if secondary_2028_inherit else "excel_blank",
        "planned_cleared": cleared,
        "planned_loaded": len(planned),
    }


def _upsert_cleaned_mortgage_scenario(conn, mortgage_id: Optional[int]) -> None:
    deltas = []
    if mortgage_id is not None:
        deltas.append(
            {
                "kind": "disable_rule",
                "rule_id": int(mortgage_id),
                "label": "Disable FY24-27 day-10 mortgage -2450.00",
            }
        )
    payload = {
        "name": SCENARIO_CLEANED_MORTGAGE,
        "description": (
            "What-if: drop Excel's FY24-27 day-10 mortgage (−$2,871.09) and keep only "
            "Loans!X11 day-11 (−$1,081.09). Baseline is Excel-parity (double mortgage). "
            "Does not change side_gig, wife allowance, or HOA stamps."
        ),
        "deltas": deltas,
    }
    existing = [s for s in db.list_scenarios(conn) if s.get("name") == SCENARIO_CLEANED_MORTGAGE]
    if existing:
        payload["id"] = existing[0]["id"]
    db.save_scenario(conn, payload)
