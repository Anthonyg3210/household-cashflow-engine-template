import pytest
"""Unit tests for EOD projection engine."""
from datetime import date

from engine.project import (
    ScenarioDelta,
    project,
    expand_rules,
    compare_scenarios,
    format_pitfall_ribbon,
    pitfall_months_by_year,
    year_pitfall_scorecard,
    filter_months_for_year,
    year_scorecard_kpis,
    breach_autopsy,
)
from engine.mitigation import (
    mitigation_suggestions,
    category_nature,
    apply_mitigation_to_planned,
    load_flexibility_config,
)


def test_eod_compounds_day_over_day():
    rules = [
        {
            "id": 1,
            "category": "Income",
            "day_of_month": 1,
            "amount": 1000,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 2,
            "category": "Rent",
            "day_of_month": 2,
            "amount": -400,
            "cadence": "monthly_dom",
            "enabled": True,
        },
    ]
    res = project(date(2026, 9, 1), date(2026, 9, 3), 100.0, rules)
    daily = {d["date"]: d for d in res["daily"]}
    assert abs(daily[date(2026, 9, 1)]["eod"] - 1100.0) < 1e-6
    assert abs(daily[date(2026, 9, 2)]["eod"] - 700.0) < 1e-6
    assert abs(daily[date(2026, 9, 3)]["eod"] - 700.0) < 1e-6


def test_actuals_override_same_date_category():
    rules = [
        {
            "id": 1,
            "category": "Rent",
            "day_of_month": 5,
            "amount": -1000,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    actuals = [{"date": "2026-09-05", "amount": -800, "category": "Rent", "label": "actual rent"}]
    res = project(date(2026, 9, 1), date(2026, 9, 5), 2000.0, rules, actuals=actuals)
    day = next(d for d in res["daily"] if d["date"] == date(2026, 9, 5))
    assert abs(day["flow_sum"] - (-800)) < 1e-6
    assert abs(day["eod"] - 1200.0) < 1e-6


def test_year_varying_paycheck():
    rules = [
        {
            "id": 1,
            "category": "Alex's Income",
            "cadence": "biweekly",
            "anchor_date": "2026-09-11",
            "interval_days": 14,
            "amount": 100,
            "amount_by_year": {2026: 4200.00, 2027: 5000.0},
            "enabled": True,
        }
    ]
    flows = expand_rules(rules, date(2026, 9, 11), date(2027, 1, 8))
    by_year = {}
    for f in flows:
        by_year.setdefault(f.date.year, []).append(f.amount)
    assert all(abs(a - 4200.00) < 1e-6 for a in by_year[2026])
    assert all(abs(a - 5000.0) < 1e-6 for a in by_year[2027])


def test_month_end_and_negative_counts():
    rules = [
        {
            "id": 1,
            "category": "Big",
            "day_of_month": 15,
            "amount": -500,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    res = project(date(2026, 9, 1), date(2026, 9, 30), 100.0, rules, warning_threshold=100)
    assert res["months"][0]["month_end"] == res["daily"][-1]["eod"]
    assert res["months"][0]["days_negative"] >= 1
    assert res["summary"]["first_breach"] == date(2026, 9, 15)


def test_scenario_one_off_changes_min_eod():
    rules = []
    base = project(date(2026, 9, 1), date(2026, 12, 31), 5000.0, rules)
    deltas = [
        ScenarioDelta(kind="one_off", amount=-4000, on_date=date(2026, 10, 1), category="Car", label="buy")
    ]
    sc = project(date(2026, 9, 1), date(2026, 12, 31), 5000.0, rules, scenario_deltas=deltas)
    assert sc["summary"]["min_eod"] < base["summary"]["min_eod"]
    assert sc["summary"]["ending_balance"] == base["summary"]["ending_balance"] - 4000


def test_compare_scenarios_baseline_and_alt():
    rules = [
        {
            "id": 1,
            "category": "Savings",
            "day_of_month": 28,
            "amount": -1000,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    scenarios = [
        {
            "id": 1,
            "name": "Cut savings 50%",
            "deltas": [
                {
                    "kind": "expense_change",
                    "category": "Savings",
                    "mode": "pct",
                    "amount": -50,
                    "start_date": "2026-09-01",
                }
            ],
        }
    ]
    cmp = compare_scenarios(
        date(2026, 9, 1), date(2026, 12, 31), 3000.0, rules, [], [], scenarios
    )
    assert cmp[0]["name"] == "Baseline"
    assert cmp[1]["summary"]["ending_balance"] > cmp[0]["summary"]["ending_balance"]


def test_dom_clamps_short_months():
    rules = [
        {
            "id": 1,
            "category": "X",
            "day_of_month": 31,
            "amount": -10,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    flows = expand_rules(rules, date(2026, 2, 1), date(2026, 2, 28))
    assert len(flows) == 1
    assert flows[0].date == date(2026, 2, 28)


def test_redirect_applies_to_same_scenario_one_off():
    rules = []
    deltas = [
        ScenarioDelta(
            kind="one_off",
            amount=8000,
            on_date=date(2026, 12, 15),
            category="Other Income",
            label="bonus",
        ),
        ScenarioDelta(
            kind="redirect",
            redirect_from_category="Other Income",
            redirect_to_category="Debt Payoff",
            on_date=date(2026, 12, 15),
            redirect_amount=8000,
            label="to debt",
        ),
    ]
    base = project(date(2026, 9, 1), date(2026, 12, 31), 2000.0, rules)
    sc = project(date(2026, 9, 1), date(2026, 12, 31), 2000.0, rules, scenario_deltas=deltas)
    assert abs(sc["summary"]["ending_balance"] - base["summary"]["ending_balance"]) < 1e-6


def test_merchant_mapper_taxonomy_v2_wells_and_dining():
    from engine.bank_import import MerchantMapper

    m = MerchantMapper.load(conn=None)
    parent, sub, legacy = m.categorize_full(
        "WELLS FARGO CARD CCPYMT     DEMO00000000001  WEB ID: DEMO0000002", -100.0
    )
    assert parent == "Work Wash"
    assert sub == "Work Travel (Reimbursed)"

    parent, sub, legacy = m.categorize_full("STARBUCKS STORE 02963 SPRINGFIELD ST 09/01", -7.0)
    assert parent == "Dining"
    assert sub == "Coffee / Cafe"

    parent, sub, legacy = m.categorize_full("CAFE C SPRINGFIELD ST 09/22", -9.0)
    assert parent == "Dining"
    assert sub == "Work Lunches"

    parent, sub, legacy = m.categorize_full("TST* FOXTAIL COFFEE - 1 VIERA FL 11/07", -15.0)
    assert parent == "Dining"
    assert sub == "Coffee / Cafe"

    parent, sub, legacy = m.categorize_full("CHICK-FIL-A #02106 SPRINGFIELD ST 10/31", -20.0)
    assert parent == "Dining"
    assert sub == "Fast Food"

    parent, sub, legacy = m.categorize_full("HOME LOAN SERVICER  LOAN", -950.00)
    assert parent == "Housing"
    assert legacy == "Home Mortgage"


def test_taxonomy_v2_json_has_parents_and_excel_map():
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parent.parent / "seed" / "taxonomy_v2.json").read_text()
    )
    assert data["version"] == 2
    names = [p["name"] for p in data["parents"]]
    for required in [
        "Housing",
        "Utilities",
        "Groceries",
        "Dining",
        "Shopping",
        "Credit Cards",
        "Auto",
        "School",
        "Income",
        "Transfers / Savings",
        "Work Wash",
    ]:
        assert required in names
    assert "Fast Food / Food Outings" in data["excel_name_to_new"]
    assert data["excel_name_to_new"]["Meriott Chase"]["parent"] == "Credit Cards"


def test_suppress_rules_through_skips_rules_keeps_planned():
    """Budget workbook planned cover suppressed dates; rules resume after."""
    rules = [
        {
            "id": 1,
            "category": "Water",
            "day_of_month": 20,
            "amount": -100,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    planned = [
        {
            "date": "2026-09-20",
            "amount": -95.00,
            "category": "Water",
            "label": "Budget workbook Water",
        }
    ]
    res = project(
        date(2026, 9, 12),
        date(2026, 10, 20),
        1000.0,
        rules,
        planned=planned,
        suppress_rules_through=date(2026, 9, 30),
    )
    sep20 = next(d for d in res["daily"] if d["date"] == date(2026, 9, 20))
    assert abs(sep20["flow_sum"] - (-95.00)) < 1e-6
    assert all(f.source == "planned" for f in sep20["flows"])
    oct20 = next(d for d in res["daily"] if d["date"] == date(2026, 10, 20))
    assert abs(oct20["flow_sum"] - (-100.0)) < 1e-6
    assert any(f.source == "rule" for f in oct20["flows"])


def test_suppress_rules_through_biweekly():
    rules = [
        {
            "id": 1,
            "category": "Alex's Income",
            "cadence": "biweekly",
            "anchor_date": "2026-09-11",
            "interval_days": 14,
            "amount": 4200.00,
            "enabled": True,
        }
    ]
    planned = [
        {"date": "2026-09-25", "amount": 4200.00, "category": "Alex's Income", "label": "FB"}
    ]
    flows = expand_rules(
        rules, date(2026, 9, 12), date(2026, 10, 31), suppress_rules_through=date(2026, 9, 30)
    )
    assert not any(f.date == date(2026, 9, 25) for f in flows)
    assert any(f.date == date(2026, 10, 9) for f in flows)
    res = project(
        date(2026, 9, 12),
        date(2026, 9, 30),
        5000.00,
        rules,
        planned=planned,
        suppress_rules_through=date(2026, 9, 30),
    )
    day = next(d for d in res["daily"] if d["date"] == date(2026, 9, 25))
    assert abs(day["flow_sum"] - 4200.00) < 1e-6


def test_pitfall_ribbon_and_year_filter():
    months = [
        {"year": 2026, "month": 11, "days_negative": 0, "days_warning": 0,
         "min_eod": 100.0, "month_end": 120.0, "first_breach": None},
        {"year": 2026, "month": 12, "days_negative": 4, "days_warning": 4,
         "min_eod": -50.0, "month_end": -40.0, "first_breach": date(2026, 12, 28)},
        {"year": 2027, "month": 1, "days_negative": 1, "days_warning": 2,
         "min_eod": -80.0, "month_end": 10.0, "first_breach": date(2027, 1, 5)},
        {"year": 2027, "month": 6, "days_negative": 0, "days_warning": 3,
         "min_eod": 20.0, "month_end": 50.0, "first_breach": None},
        {"year": 2028, "month": 3, "days_negative": 0, "days_warning": 0,
         "min_eod": 200.0, "month_end": 250.0, "first_breach": None},
    ]
    assert format_pitfall_ribbon(months, years=[2026, 2027, 2028]) == (
        "2026: Dec · 2027: Jan · 2028: none"
    )
    assert format_pitfall_ribbon(months, key="days_warning", years=[2026, 2027, 2028]) == (
        "2026: Dec · 2027: Jan, Jun · 2028: none"
    )
    assert pitfall_months_by_year(months)[2026] == ["Dec"]
    sc = year_pitfall_scorecard(months, years=[2026, 2027, 2028])
    assert [(e["year"], e["is_bad"], e["detail"], e["red_month_count"]) for e in sc] == [
        (2026, True, "Dec", 1),
        (2027, True, "Jan", 1),
        (2028, False, "All clear", 0),
    ]
    only_2027 = filter_months_for_year(months, 2027)
    assert [m["month"] for m in only_2027] == [1, 6]
    k = year_scorecard_kpis(only_2027)
    assert k["red_months"] == 1
    assert abs(k["min_eod"] - (-80.0)) < 1e-9
    assert abs(k["ending_balance"] - 50.0) < 1e-9
    assert filter_months_for_year(months, None) == months


def test_breach_autopsy_synthetic_jan_style():
    """Savings + Wife allowance + Gas on day 28; Alex recovers next day."""
    rules = [
        {
            "id": 1,
            "category": "Savings",
            "label": "Savings",
            "day_of_month": 28,
            "amount": -3500.0,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 2,
            "category": "Partner Allowance",
            "label": "Partner Allowance",
            "day_of_month": 28,
            "amount": -2500.0,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 3,
            "category": "Gas Bill",
            "label": "Gas Bill",
            "day_of_month": 28,
            "amount": -44.0,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 4,
            "category": "Alex's Income",
            "label": "Alex paycheck",
            "cadence": "biweekly",
            "anchor_date": "2027-01-29",
            "interval_days": 14,
            "amount": 4200.0,
            "enabled": True,
        },
    ]
    # Start Jan 27 with prior EOD ~5182 so day 28 goes red
    res = project(date(2027, 1, 27), date(2027, 1, 30), 5182.0, rules)
    auto = breach_autopsy(res["daily"], 2027, 1)
    assert auto is not None
    assert auto["first_breach"] == date(2027, 1, 28)
    assert abs(auto["prior_eod"] - 5182.0) < 1e-6
    assert auto["breach_eod"] < 0
    cats = [f["category"] for f in auto["largest_outflows"]]
    assert cats[:2] == ["Savings", "Partner Allowance"]
    assert "Gas Bill" in cats
    assert auto["next_inflow"] is not None
    assert auto["next_inflow"]["date"] == date(2027, 1, 29)
    assert "Alex" in auto["next_inflow"]["category"]
    assert "Savings" in auto["cause_summary"]
    assert "Partner Allowance" in auto["cause_summary"]
    assert auto["suggestion"]  # flexible outflows day-before paycheck
    # by breach_date
    auto2 = breach_autopsy(res["daily"], breach_date=date(2027, 1, 28))
    assert auto2["first_breach"] == date(2027, 1, 28)
    assert breach_autopsy(res["daily"], 2027, 2) is None


@pytest.mark.skip(reason="requires production live DB fixtures; not in template")
def test_breach_autopsy_live_jan_2027():
    """Live seeded project: Jan 2027 first breach calls out Savings + Wife allowance."""
    from engine import db
    from engine.seed_load import ensure_seeded

    conn = db.connect()
    ensure_seeded(conn)
    settings = db.get_settings(conn)
    assert abs(settings["start_balance"] - 5000.00) < 1e-6
    # Exclude applied mitigation:* overlays so this asserts the unmitigated breach.
    planned = [
        p
        for p in db.list_planned(conn)
        if not str(p.get("source") or "").startswith("mitigation:")
    ]
    res = project(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        db.list_rules(conn),
        planned,
        db.list_actuals(conn),
        None,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )
    auto = breach_autopsy(res["daily"], 2027, 1)
    assert auto is not None
    assert auto["first_breach"] == date(2027, 1, 28)
    # prior_eod includes Demo Cleaners −$180/mo (Oct 2026–Jan 2027) vs Excel-only baseline
    assert abs(auto["prior_eod"] - 4412.17) < 0.02
    assert abs(auto["breach_eod"] - (-1631.65)) < 0.02
    out_cats = [f["category"] for f in auto["largest_outflows"]]
    assert out_cats[0] == "Savings"
    assert out_cats[1] == "Partner Allowance"
    assert any(c == "Gas Bill" for c in out_cats)
    assert auto["next_inflow"]["date"] == date(2027, 1, 29)
    assert "Alex" in auto["next_inflow"]["category"]
    assert "Savings" in auto["cause_summary"] and "Partner Allowance" in auto["cause_summary"]


def test_category_nature_config():
    cfg = load_flexibility_config()
    assert "Savings" in cfg["flexible"]
    assert "Partner Allowance" in cfg["flexible"]
    assert "Home Mortgage" in cfg["fixed"]
    assert category_nature("Savings") == "flexible"
    assert category_nature("Home Mortgage") == "fixed"
    assert category_nature("Gas Bill") == "fixed"
    assert category_nature("Jordan's Income") == "income_timing"


@pytest.mark.skip(reason="requires production live DB fixtures; not in template")
def test_mitigation_simulation_jan_2027_live():
    """Jan 2027: before apply min negative; Savings 28→29 clears red (Wife not required)."""
    from engine import db
    from engine.seed_load import ensure_seeded

    conn = db.connect()
    ensure_seeded(conn)
    settings = db.get_settings(conn)
    rules = db.list_rules(conn)
    # Strip already-applied mitigation overlays to test the pre-apply path.
    planned = [
        p
        for p in db.list_planned(conn)
        if not str(p.get("source") or "").startswith("mitigation:")
    ]
    actuals = db.list_actuals(conn)
    res = project(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        rules,
        planned,
        actuals,
        None,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )
    jan = [d for d in res["daily"] if d["date"].year == 2027 and d["date"].month == 1]
    assert min(d["eod"] for d in jan) < 0
    assert sum(1 for d in jan if d["eod"] < 0) >= 1

    auto = breach_autopsy(res["daily"], 2027, 1)
    mit = mitigation_suggestions(
        res["daily"],
        2027,
        1,
        start_date=settings["start_date"],
        end_date=settings["end_date"],
        start_balance=settings["start_balance"],
        rules=rules,
        planned=planned,
        actuals=actuals,
        warning_threshold=settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
        autopsy=auto,
    )
    assert mit is not None
    assert mit["baseline"]["min_eod"] < 0
    assert mit["payday"] == date(2027, 1, 29)
    natures = {c["category"]: c["nature"] for c in mit["classified_outflows"]}
    assert natures.get("Savings") == "flexible"
    assert natures.get("Partner Allowance") == "flexible"
    assert natures.get("Gas Bill") == "fixed"

    # Ranked: Savings shift should clear and be preferred
    flex = [p for p in mit["proposals"] if p["kind"] == "shift_flexible"]
    assert flex[0]["category"] == "Savings"
    assert flex[0]["from_date"] == date(2027, 1, 28)
    assert flex[0]["suggested_to_date"] == date(2027, 1, 29)
    assert flex[0]["simulation"]["clears_first_breach"] is True
    assert flex[0]["simulation"]["new_min_eod"] > 0

    assert mit["recommended"][0]["category"] == "Savings"
    assert mit["plan_clears_breach"] is True
    assert mit["plan_min_eod"] > 0
    # Wife not required once Savings moves
    assert [r["category"] for r in mit["recommended"]] == ["Savings"]

    # Fixed note present, not applicable
    fixed = [p for p in mit["proposals"] if p["kind"] == "fixed_note"]
    assert any(p["category"] == "Gas Bill" for p in fixed)
    assert all(p["applicable"] is False for p in fixed)

    new_planned = apply_mitigation_to_planned(planned, mit)
    res2 = project(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        rules,
        new_planned,
        actuals,
        None,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )
    jan2 = [d for d in res2["daily"] if d["date"].year == 2027 and d["date"].month == 1]
    assert sum(1 for d in jan2 if d["eod"] < 0) == 0
    assert min(d["eod"] for d in jan2) > 0
    # Savings appears on the 29th after overlay
    day29 = next(d for d in jan2 if d["date"] == date(2027, 1, 29))
    sav29 = sum(f.amount for f in day29["flows"] if f.category == "Savings")
    assert abs(sav29 - (-3500.0)) < 1e-6


def test_mitigation_synthetic_prefer_savings_then_allowance():
    """When Savings alone is not enough, recommended plan adds Wife allowance."""
    rules = [
        {
            "id": 1,
            "category": "Savings",
            "label": "Savings",
            "day_of_month": 15,
            "amount": -200.0,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 2,
            "category": "Partner Allowance",
            "label": "Partner Allowance",
            "day_of_month": 15,
            "amount": -400.0,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 3,
            "category": "Home Mortgage",
            "label": "Home Mortgage",
            "day_of_month": 15,
            "amount": -300.0,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 4,
            "category": "Alex's Income",
            "label": "Alex paycheck",
            "day_of_month": 16,
            "amount": 700.0,
            "cadence": "monthly_dom",
            "enabled": True,
        },
    ]
    # Start 350 → day15: 350-200-400-300 = -550 (red). Paycheck +700 on 16th.
    # Savings alone → day15 still red. Both flexible → day15 = +50; day16 stays non-negative.
    res = project(date(2027, 3, 14), date(2027, 3, 17), 350.0, rules)
    mit = mitigation_suggestions(
        res["daily"],
        2027,
        3,
        start_date=date(2027, 3, 14),
        end_date=date(2027, 3, 17),
        start_balance=350.0,
        rules=rules,
        planned=[],
        actuals=[],
    )
    assert mit["baseline"]["first_breach"] == date(2027, 3, 15)
    sav = next(p for p in mit["proposals"] if p["category"] == "Savings")
    assert sav["simulation"]["clears_first_breach"] is False
    assert [r["category"] for r in mit["recommended"]] == ["Savings", "Partner Allowance"]
    assert mit["plan_clears_breach"] is True
    rocket = next(p for p in mit["proposals"] if p["kind"] == "fixed_note")
    assert rocket["category"] == "Home Mortgage"


@pytest.mark.skip(reason="requires production live DB fixtures; not in template")
def test_calendar_effective_savings_jan2027_on_29th():
    """Applied Jan mitigation: Savings lands on effective day 29 (not 28)."""
    from engine import db
    from engine.seed_load import ensure_seeded
    from engine.calendar_view import month_bill_checklist, effective_day_flows

    conn = db.connect()
    ensure_seeded(conn)
    st = db.get_settings(conn)
    assert abs(float(st["start_balance"]) - 5000.00) < 0.01
    res = project(
        st["start_date"],
        st["end_date"],
        st["start_balance"],
        db.list_rules(conn),
        db.list_planned(conn),
        db.list_actuals(conn),
        None,
        st["warning_threshold"],
        suppress_rules_through=st.get("suppress_rules_through"),
    )
    bills = month_bill_checklist(res["daily"], 2027, 1)
    savings = [b for b in bills if b["category"] == "Savings"]
    assert savings, "expected Savings on Jan 2027 checklist"
    days = {b["day"] for b in savings}
    assert 29 in days, f"Savings should appear on 29th, got days={days}"
    assert 28 not in days, f"cancelled 28th should not show, got days={days}"
    moved_29 = [b for b in savings if b["day"] == 29 and b["moved"]]
    assert moved_29, "Jan 29 Savings should be marked moved"
    # Net amount on 29th
    assert abs(moved_29[0]["amount"] - (-3500.0)) < 0.01


def test_net_worth_snapshot_blank_and_roundtrip(tmp_path):
    from engine.net_worth import load_snapshot, save_snapshot, format_balance_display

    p = tmp_path / "nw.json"
    blank = load_snapshot(p)
    assert blank["fidelity_brokerage_balance"] is None
    assert blank["savings_balance"] is None
    assert format_balance_display(None) == "—"
    assert format_balance_display(None, empty="Not set yet") == "Not set yet"

    saved = save_snapshot(
        fidelity_brokerage_balance=12345.5,
        savings_balance=None,
        balances_as_of="2026-09-12",
        path=p,
    )
    assert saved["fidelity_brokerage_balance"] == 12345.5
    assert saved["savings_balance"] is None
    assert saved["balances_as_of"] == "2026-09-12"
    assert format_balance_display(saved["fidelity_brokerage_balance"]) == "$12,345.50"
