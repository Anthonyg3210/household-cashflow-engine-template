import pytest
"""Excel-parity month-end checks (Oct 2026+ Budget workbook / dashboard)."""
from datetime import date

from engine.excel_parity import EXCEL_MONTH_ENDS, extra_planned, extra_rules

# Twin includes intentional Oct 2 side_gig (+$600) not in original Excel stamps.
SIDE_GIG_OCT2_DELTA = 550.0

def _excel_me_with_oct2(year: int, month: int) -> float:
    base = EXCEL_MONTH_ENDS[(year, month)]
    if (year, month) >= (2026, 10):
        return base + SIDE_GIG_OCT2_DELTA
    return base
from engine.project import expand_rules, project


def _fy24_27_core_rules():
    """Minimal Data Input FY24-27 DOM + paychecks used by Oct+ VLOOKUP months."""
    expenses = [
        ("Electric", 2, -180.00),
        ("Student Loans", 6, -650.00),
        ("Car Insurance", 7, -240.00),
        ("Streaming Bundle", 8, -45.0),
        ("Car Wash Club", 10, -40.00),
        ("YouTube Subscription", 10, -13.99),
        ("Home Mortgage", 11, -950.00),
        ("Jordan's Craft Club", 19, -12.99),
        ("Water", 20, -95.00),
        ("Internet", 20, -90.0),
        ("Lawn Service", 20, -80.0),
        ("Fitness Membership", 23, -44.00),
        ("Video Stream", 24, -15.99),
        ("Park Pass", 27, -120.00),
        ("Gas Bill", 28, -45.00),
        ("Savings", 28, -2000.0),
    ]
    rules = []
    for i, (cat, dom, amt) in enumerate(expenses, start=1):
        rules.append(
            {
                "id": i,
                "category": cat,
                "label": cat,
                "day_of_month": dom,
                "amount": amt,
                "cadence": "monthly_dom",
                "start_date": "2026-09-01",
                "end_date": "2027-12-31",
                "enabled": True,
            }
        )
    rules.append(
        {
            "id": 50,
            "category": "Alex's Income",
            "label": "Alex paycheck (biweekly)",
            "cadence": "biweekly",
            "anchor_date": "2026-09-11",
            "interval_days": 14,
            "amount": 4200.00,
            "amount_by_year": {2026: 4200.00, 2027: 4200.00},
            "start_date": "2026-09-01",
            "enabled": True,
        }
    )
    rules.append(
        {
            "id": 51,
            "category": "Jordan's Income",
            "label": "Jordan income (monthly)",
            "day_of_month": 8,
            "amount": 1500.0,
            "cadence": "monthly_dom",
            "start_date": "2026-09-01",
            "enabled": True,
        }
    )
    return rules


def _parity_bundle():
    rules = _fy24_27_core_rules() + extra_rules(include_day10_mortgage=True)
    planned = extra_planned()
    return rules, planned


def test_double_mortgage_expands_oct_10_and_11():
    rules = extra_rules(include_day10_mortgage=True)
    rules.append(
        {
            "category": "Home Mortgage",
            "day_of_month": 11,
            "amount": -950.00,
            "cadence": "monthly_dom",
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "enabled": True,
        }
    )
    flows = expand_rules(rules, date(2026, 10, 1), date(2026, 10, 31))
    rockets = [f for f in flows if f.category == "Home Mortgage"]
    by_day = {f.date: f.amount for f in rockets}
    assert abs(by_day[date(2026, 10, 10)] - (-2450.00)) < 1e-6
    assert abs(by_day[date(2026, 10, 11)] - (-950.00)) < 1e-6


@pytest.mark.skip(reason="side-gig stamp dates are production workbook specific")
def test_side_gig_includes_oct_2_opposite_alex_fridays():
    """Oct 2 closes the opposite-Friday streak (Alex anchor 2026-09-11)."""
    rules = extra_rules(include_day10_mortgage=False)
    side_gig = [r for r in rules if "side_gig" in (r.get("label") or "").lower()]
    assert len(side_gig) == 1
    assert side_gig[0].get("anchor_date") == "2026-10-02"
    assert side_gig[0].get("start_date") == "2026-10-02"
    flows = expand_rules(side_gig, date(2026, 10, 1), date(2027, 2, 28))
    dates = {f.date for f in flows}
    assert date(2026, 10, 2) in dates
    assert date(2026, 10, 16) in dates
    assert date(2026, 10, 30) in dates
    assert date(2027, 2, 19) in dates
    assert date(2027, 3, 5) not in dates
    assert all(abs(f.amount - 600.0) < 1e-6 for f in flows)


@pytest.mark.skip(reason="Excel byte-parity is production-specific; template uses synthetic seed")
def test_oct_2026_month_end_matches_excel():
    rules, planned = _parity_bundle()
    # Start at Excel Sep month-end so Oct is a clean VLOOKUP+overlay month
    res = project(
        date(2026, 10, 1),
        date(2026, 10, 31),
        EXCEL_MONTH_ENDS[(2026, 9)],
        rules,
        planned=planned,
    )
    assert abs(res["months"][0]["month_end"] - _excel_me_with_oct2(2026, 10)) < 1.0


@pytest.mark.skip(reason="Excel byte-parity is production-specific; template uses synthetic seed")
def test_oct_2026_through_dec_2027_month_ends():
    rules, planned = _parity_bundle()
    res = project(
        date(2026, 10, 1),
        date(2027, 12, 31),
        EXCEL_MONTH_ENDS[(2026, 9)],
        rules,
        planned=planned,
    )
    for m in res["months"]:
        key = (m["year"], m["month"])
        expected = _excel_me_with_oct2(key[0], key[1])
        assert abs(m["month_end"] - expected) < 1.0, (
            f"{m['label']} twin={m['month_end']:.2f} expected={expected:.2f}"
        )


@pytest.mark.skip(reason="Excel byte-parity is production-specific; template uses synthetic seed")
def test_sep_override_then_oct_parity():
    """Sep planned + suppress keeps 2200.00; Oct uses Excel-parity rules."""
    rules, planned = _parity_bundle()
    sep_planned = [
        {"date": "2026-09-13", "amount": -2450.00, "category": "Home Mortgage"},
        {"date": "2026-09-13", "amount": 1500.0, "category": "Jordan's Income"},
        {"date": "2026-09-18", "amount": 600.0, "category": "Other Income"},
        {"date": "2026-09-20", "amount": -95.00, "category": "Water"},
        {"date": "2026-09-20", "amount": -100.0, "category": "AT&T"},
        {"date": "2026-09-20", "amount": -100.0, "category": "Lawn Service"},
        {"date": "2026-09-23", "amount": -44.00, "category": "Jordan's Craft Club"},
        {"date": "2026-09-24", "amount": -15.99, "category": "Video Stream"},
        {"date": "2026-09-25", "amount": 4200.00, "category": "Alex's Income"},
        {"date": "2026-09-28", "amount": -43.82, "category": "Gas Bill"},
        {"date": "2026-09-28", "amount": -3500.0, "category": "Savings"},
        {"date": "2026-09-28", "amount": -2500.0, "category": "Partner Allowance"},
    ]
    res = project(
        date(2026, 9, 12),
        date(2026, 10, 31),
        5000.00,
        rules,
        planned=sep_planned + planned,
        suppress_rules_through=date(2026, 9, 30),
    )
    by = {(m["year"], m["month"]): m["month_end"] for m in res["months"]}
    assert abs(by[(2026, 9)] - EXCEL_MONTH_ENDS[(2026, 9)]) < 1.0
    assert abs(by[(2026, 10)] - EXCEL_MONTH_ENDS[(2026, 10)]) < 1.0


def test_ensure_seeded_upserts_adi_on_existing_db(tmp_path):
    """Cloud-style: rich DB missing Demo Cleaners still gets the overlay on every boot."""
    import sqlite3

    from engine import db as dbmod
    from engine.excel_parity import LABEL_DEMO_CLEANING
    from engine.seed_load import ensure_seeded

    # Avoid db.connect() — it may copy cloud_bootstrap.db when the path is new.
    path = tmp_path / "cashflow.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)
    dbmod.save_settings(
        conn,
        {
            "start_date": "2026-09-12",
            "end_date": "2029-09-12",
            "start_balance": 5000.00,
            "warning_threshold": 100.0,
            "breach_threshold": 0.0,
            "suppress_rules_through": "2026-09-30",
        },
    )
    dbmod.set_setting(conn, "mortgage_policy", "excel_double")
    dbmod.set_setting(conn, "secondary_2028_policy", "excel_blank")
    # Pretend Cloud already has rules but never got the Demo Cleaners overlay.
    dbmod.upsert_rule(
        conn,
        {
            "category": "Home Mortgage",
            "label": "Mortgage day 11",
            "day_of_month": 11,
            "amount": -950.00,
            "cadence": "monthly_dom",
            "start_date": "2026-09-01",
            "enabled": True,
        },
    )
    assert not any(
        (r.get("label") or "").startswith(LABEL_DEMO_CLEANING) for r in dbmod.list_rules(conn)
    )

    summary = ensure_seeded(conn)
    assert summary.get("already_seeded") is True
    assert "excel_parity" in summary

    demo_cleaners = [
        r
        for r in dbmod.list_rules(conn)
        if (r.get("label") or "").startswith(LABEL_DEMO_CLEANING) and r.get("enabled")
    ]
    assert len(demo_cleaners) == 1
    assert demo_cleaners[0]["start_date"] == "2026-10-01"
    assert demo_cleaners[0]["end_date"] == "2029-09-12"
    assert abs(float(demo_cleaners[0]["amount"]) + 180.0) < 1e-9
