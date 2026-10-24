"""Excel-parity rule overlays for Oct 2026+ Budget workbook month-ends.

Data Input VLOOKUP is the backbone, but Budget workbook still hard-stamps
income, partner allowance (−2500 through Feb 2027), side_gig $548.73, HOA,
pressure-cleaning, and the Mar-2027 ~$23.8k other-income. This module applies
those overlays so twin month_end matches Summary Dashboard / row 90.

Does not modify the original Excel workbook.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from . import db

PLANNED_SOURCE = "excel_parity_forecast"

LABEL_MORTGAGE_D10 = "Home Mortgage (Excel FY24-27 day 10)"
LABEL_PARTNER_2500 = "Partner Allowance (Excel -2500 through 2027-02)"
LABEL_PARTNER_2400 = "Partner Allowance (Data Input -2400 from 2027-03)"
LABEL_SIDE_GIG = "Other Income (Excel side-gig / budget stamps stamps)"
LABEL_OLD_SIDE_GIG = "Jordan side gig (biweekly, 2026 only)"
LABEL_DEMO_CLEANING = "Demo Cleaners service ($176.40/mo)"
SCENARIO_CLEANED_MORTGAGE = "Cleaned single-mortgage (what-if)"

# Cached Summary Dashboard col C / Budget workbook row-90 month totals
EXCEL_MONTH_ENDS = {
    (2026, 9): 2174.09,
    (2026, 10): 1918.37,
    (2026, 11): 1587.62,
    (2026, 12): -413.85,
    (2027, 1): 2386.14,
    (2027, 2): 3219.53,
    (2027, 3): 23968.41,
    (2027, 4): 21483.76,
    (2027, 5): 19027.18,
    (2027, 6): 16492.63,
    (2027, 7): 17986.25,
    (2027, 8): 15513.94,
    (2027, 9): 12978.31,
    (2027, 10): 10524.67,
    (2027, 11): 7986.42,
    (2027, 12): 9017.58,
    (2028, 1): 9483.26,
    (2028, 2): 10016.91,
    (2028, 3): 10792.44,
    (2028, 4): 11518.73,
    (2028, 5): 11984.37,
    (2028, 6): 17023.15,
    (2028, 7): 17486.92,
    (2028, 8): 18012.68,
    (2028, 9): 18793.21,
    (2028, 10): 19517.46,
    (2028, 11): 19982.73,
    (2028, 12): 24016.38,
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
                "amount": -2463.19,
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
                "label": LABEL_PARTNER_2500,
                "day_of_month": 28,
                "amount": -2500.0,
                "cadence": "monthly_dom",
                "start_date": "2026-10-01",
                "end_date": "2027-02-28",
                "enabled": True,
            },
            {
                "category": "Partner Allowance",
                "label": LABEL_PARTNER_2400,
                "day_of_month": 28,
                "amount": -2400.0,
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
                "amount": 548.73,
                "amount_by_year": {2026: 548.73, 2027: 548.73},
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
        # Quarterly pressure cleaning (Data Input!AL65 = -149.75), Excel placement dates
        ("2026-11-20", -149.75, "Home Pressure Cleaning"),
        ("2027-02-20", -149.75, "Home Pressure Cleaning"),
        ("2027-05-20", -149.75, "Home Pressure Cleaning"),
        ("2027-08-20", -149.75, "Home Pressure Cleaning"),
        ("2027-11-20", -149.75, "Home Pressure Cleaning"),
        ("2028-02-20", -149.75, "Home Pressure Cleaning"),
        ("2028-05-19", -149.75, "Home Pressure Cleaning"),
        ("2028-08-20", -149.75, "Home Pressure Cleaning"),
        ("2028-11-20", -149.75, "Home Pressure Cleaning"),
        # Annual HOA (Data Input!AL6/AL7/AL8) — Dec placements + Jul 1 -$251.30
        ("2026-12-25", -268.40, "Homeowners Association Fee 1st"),
        ("2026-12-25", -268.40, "Homeowners Association Fee 2dn"),
        ("2026-12-25", -712.55, "Homeowners Community Dues"),
        ("2027-07-01", -251.30, "Homeowners Association Fee 1st"),
        ("2027-12-24", -268.40, "Homeowners Association Fee 1st"),
        ("2027-12-24", -268.40, "Homeowners Association Fee 2dn"),
        ("2027-12-24", -712.55, "Homeowners Community Dues"),
        ("2028-07-01", -251.30, "Homeowners Association Fee 1st"),
        ("2028-12-26", -268.40, "Homeowners Association Fee 1st"),
        ("2028-12-26", -268.40, "Homeowners Association Fee 2dn"),
        ("2028-12-26", -712.55, "Homeowners Community Dues"),
        # Budget workbook Other Income hardcoded
        ("2027-03-11", 23847.16, "Other Income"),
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
    harbor_d10 = None
    for r in db.list_rules(conn):
        if (
            r.get("category") == "Home Mortgage"
            and int(r.get("day_of_month") or 0) == 10
            and abs(float(r.get("amount") or 0)) > 2000
            and (r.get("start_date") or "") < "2028-01-01"
        ):
            harbor_d10 = r
            break

    if prefer_single_mortgage:
        if harbor_d10 and harbor_d10.get("enabled", True):
            rr = dict(harbor_d10)
            rr["enabled"] = False
            db.upsert_rule(conn, rr)
        mortgage_id = harbor_d10["id"] if harbor_d10 else None
    else:
        if harbor_d10:
            rr = dict(harbor_d10)
            rr["label"] = LABEL_MORTGAGE_D10
            rr["enabled"] = True
            rr["end_date"] = "2027-12-31"
            mortgage_id = db.upsert_rule(conn, rr)
        else:
            mortgage_id = _upsert_by_label(conn, extra_rules(include_day10_mortgage=True)[0])

    # --- Disable leftover unsplit partner allowance (−2400 for all FY24-27) ---
    overlay_labels = {LABEL_PARTNER_2500, LABEL_PARTNER_2400, LABEL_MORTGAGE_D10, LABEL_SIDE_GIG}
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
    # Excel FY24–27 Data Input omits cleaning; the household pays Demo Cleaners ~$176.40 most months.
    # Sep 2026 already paid — forecast from Oct 2026 through end of twin (2029)
    # until Alex says otherwise. One continuous rule (not split FY28 day-20).
    # Note: Excel month-end targets then diverge by −$176.40/mo vs workbook.
    cleaner_all = [
        r
        for r in db.list_rules(conn)
        if r.get("category") == "Home Cleaning"
        or (r.get("label") or "").startswith(LABEL_DEMO_CLEANING)
    ]
    horizon_end = (db.get_settings(conn).get("end_date") or date(2029, 9, 12)).isoformat()
    cleaner_payload = {
        "category": "Home Cleaning",
        "label": LABEL_DEMO_CLEANING,
        "day_of_month": 15,
        "amount": -176.40,
        "amount_by_year": {},
        "cadence": "monthly_dom",
        "start_date": "2026-10-01",
        "end_date": horizon_end,
        "enabled": True,
    }
    if cleaner_all:
        primary = next(
            (r for r in cleaner_all if (r.get("label") or "").startswith(LABEL_DEMO_CLEANING)),
            cleaner_all[0],
        )
        cleaner_payload["id"] = primary["id"]
        db.upsert_rule(conn, cleaner_payload)
        for r in cleaner_all:
            if r["id"] != primary["id"] and r.get("enabled", True):
                rr = dict(r)
                rr["enabled"] = False
                db.upsert_rule(conn, rr)
    else:
        db.upsert_rule(conn, cleaner_payload)

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
                prior = aby.get("2027") or r.get("amount") or 1412.85
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
                "label": "Disable FY24-27 day-10 mortgage -2463.19",
            }
        )
    payload = {
        "name": SCENARIO_CLEANED_MORTGAGE,
        "description": (
            "What-if: drop Excel's FY24-27 day-10 mortgage (−$2,450.00) and keep only "
            "Loans day-11 (−$947.62). Baseline is Excel-parity (double mortgage). "
            "Does not change side_gig, partner allowance, or HOA stamps."
        ),
        "deltas": deltas,
    }
    existing = [s for s in db.list_scenarios(conn) if s.get("name") == SCENARIO_CLEANED_MORTGAGE]
    if existing:
        payload["id"] = existing[0]["id"]
    db.save_scenario(conn, payload)
