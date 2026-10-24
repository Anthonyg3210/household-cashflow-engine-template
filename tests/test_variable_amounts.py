"""Focused tests for Forecast CONVERGE change set C (variable amounts + Gas)."""
from __future__ import annotations
import pytest

from datetime import date

from engine.project import expand_rules
from engine.variable_amounts import (
    VARIABLE_APPLY_FROM,
    build_plan,
    apply_variable_override,
    oct_plus_electric_water_totals,
    plain_english_variable_detail_lines,
    plain_english_variable_sentence,
    variable_ui_rows,
)


def _electric_actuals_fixture():
    """Bank-like monthly Electric history ending Sep 2026 → 3-mo avg ≈ 251.97."""
    months = {
        "2025-10": -240.15,
        "2025-11": -215.40,
        "2025-12": -150.25,
        "2026-01": -120.10,
        "2026-02": -125.35,
        "2026-03": -130.45,
        "2026-04": -125.20,
        "2026-05": -140.30,
        "2026-06": -175.60,
        "2026-07": -185.25,
        "2026-08": -290.10,
        "2026-09": -280.55,
    }
    rows = []
    for ym, amt in months.items():
        rows.append(
            {
                "date": f"{ym}-04",
                "amount": amt,
                "category": "Electric",
                "label": "DEMO ELECTRIC",
                "source": "bank_csv",
                "enabled": True,
            }
        )
    return rows


def test_electric_recent_regime_uses_3mo_avg():
    plan = build_plan("Electric", _electric_actuals_fixture(), as_of=date(2026, 9, 15))
    assert plan.n_good >= 12
    assert plan.avg3 is not None
    assert abs(plan.avg3 - 251.966667) < 0.01
    assert plan.avg12 is not None
    assert plan.recent_regime is True
    amt, method = plan.amount_for(date(2026, 10, 3))
    assert abs(amt - 251.966667) < 0.01
    assert "recent regime" in method


def test_electric_expand_rules_replaces_oct_plus_not_sep():
    rules = [
        {
            "id": 3,
            "category": "Electric",
            "label": "Electric",
            "day_of_month": 3,
            "amount": -180.00,
            "cadence": "monthly_dom",
            "start_date": "2026-09-01",
            "end_date": "2027-12-31",
            "enabled": True,
        }
    ]
    actuals = _electric_actuals_fixture()
    flows = expand_rules(
        rules,
        date(2026, 9, 1),
        date(2026, 11, 3),
        suppress_rules_through=date(2026, 9, 30),
        actuals=actuals,
    )
    by = {f.date: f.amount for f in flows}
    assert date(2026, 9, 3) not in by  # Sep suppress intact
    assert abs(by[date(2026, 10, 3)] - (-251.966667)) < 0.01
    assert abs(by[date(2026, 11, 3)] - (-251.966667)) < 0.01


def test_no_double_count_variable_replaces_not_adds():
    rules = [
        {
            "id": 3,
            "category": "Electric",
            "label": "Electric",
            "day_of_month": 3,
            "amount": -180.00,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    actuals = _electric_actuals_fixture()
    flows = expand_rules(
        rules,
        date(2026, 10, 1),
        date(2026, 10, 31),
        actuals=actuals,
    )
    assert len(flows) == 1
    # Must be method amount, NOT -(180.00 + 251.97)
    assert abs(flows[0].amount - (-251.966667)) < 0.01
    assert abs(flows[0].amount) < 300  # not double


def test_water_keeps_rule_amount():
    rules = [
        {
            "id": 4,
            "category": "Water",
            "label": "Water",
            "day_of_month": 20,
            "amount": -95.00,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    # Even with wild actuals, Water stays at rule amount (label-only variable)
    actuals = [
        {
            "date": "2026-08-20",
            "amount": -999.0,
            "category": "Water",
            "source": "bank_csv",
            "enabled": True,
        }
    ] * 12
    flows = expand_rules(
        rules,
        date(2026, 10, 1),
        date(2026, 10, 31),
        actuals=actuals,
    )
    assert len(flows) == 1
    assert abs(flows[0].amount - (-95.00)) < 1e-6


@pytest.mark.skip(reason="production catalog/live-DB specific; template uses synthetic seed")
def test_gas_amount_updated_in_live_db():
    from engine import db

    conn = db.connect()
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT id, amount, day_of_month FROM recurring_rules WHERE category='Gas Bill' ORDER BY id"
        )
    ]
    assert rows, "expected Gas Bill rules"
    for r in rows:
        assert abs(float(r["amount"]) - (-45.00)) < 1e-6
        assert int(r["day_of_month"]) == 28


def test_sep_suppress_still_blocks_variable_categories():
    rules = [
        {
            "id": 3,
            "category": "Electric",
            "day_of_month": 3,
            "amount": -180.00,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 4,
            "category": "Water",
            "day_of_month": 20,
            "amount": -95.00,
            "cadence": "monthly_dom",
            "enabled": True,
        },
    ]
    flows = expand_rules(
        rules,
        date(2026, 9, 1),
        date(2026, 9, 30),
        suppress_rules_through=date(2026, 9, 30),
        actuals=_electric_actuals_fixture(),
    )
    assert flows == []


def test_variable_override_before_oct_unchanged():
    amt = apply_variable_override(
        "Electric",
        date(2026, 9, 3),
        -180.00,
        actuals=_electric_actuals_fixture(),
    )
    assert abs(amt - (-180.00)) < 1e-6
    assert VARIABLE_APPLY_FROM == date(2026, 10, 1)


def test_oct_plus_totals_old_vs_new():
    rules = [
        {
            "id": 3,
            "category": "Electric",
            "day_of_month": 3,
            "amount": -180.00,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 4,
            "category": "Water",
            "day_of_month": 20,
            "amount": -95.00,
            "cadence": "monthly_dom",
            "enabled": True,
        },
        {
            "id": 5,
            "category": "Gas Bill",
            "day_of_month": 28,
            "amount": -45.00,
            "cadence": "monthly_dom",
            "enabled": True,
        },
    ]
    totals = oct_plus_electric_water_totals(
        rules,
        _electric_actuals_fixture(),
        date(2026, 10, 1),
        date(2026, 10, 31),
        suppress_rules_through=date(2026, 9, 30),
    )
    # Oct: Electric method + Water keep + Gas keep
    expected_old = 180.00 + 95.00 + 45.00
    expected_new = 251.966667 + 95.00 + 45.00
    assert abs(totals["old_initiated"] - expected_old) < 0.02
    assert abs(totals["new_model"] - expected_new) < 0.02
    assert totals["old_count"] == totals["new_count"] == 3


@pytest.mark.skip(reason="production catalog/live-DB specific; template uses synthetic seed")
def test_locked_items_untouched_in_db():
    from engine import db

    conn = db.connect()
    settings = db.get_settings(conn)
    assert settings.get("suppress_rules_through") == date(2026, 9, 30)
    harbor = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'harbor%'"
        )
    }
    assert harbor.get("mortgage_policy") == "excel_double"
    assert harbor.get("harbor_dom") == "11"
    att = [
        float(r["amount"])
        for r in db.list_rules(conn)
        if r.get("category") == "Mobile Phone" and r.get("enabled", True)
    ]
    assert att and all(abs(a - (-100.0)) < 1e-6 for a in att)
    sav = [
        float(r["amount"])
        for r in db.list_rules(conn)
        if r.get("category") == "Savings" and r.get("enabled", True)
    ]
    assert sav and all(abs(a - (-2400.0)) < 1e-6 for a in sav)
    demo_cleaners = [
        float(r["amount"])
        for r in db.list_rules(conn)
        if r.get("category") == "Home Cleaning" and r.get("enabled", True)
    ]
    assert demo_c and all(abs(a - (-176.40)) < 1e-6 for a in demo_c)


@pytest.mark.skip(reason="production catalog/live-DB specific; template uses synthetic seed")
def test_catalog_amount_class_metadata():
    from engine.forecast_guard import load_essentials_catalog, clear_catalog_cache

    clear_catalog_cache()
    cat = load_essentials_catalog()
    by_id = {e["id"]: e for e in cat["essentials"]}
    assert by_id["electric"]["amount_class"] == "variable"
    assert by_id["water"]["amount_class"] == "variable"
    assert by_id["gas"]["amount_class"] == "variable"
    assert by_id["gas"]["apply_variable_method"] is False
    assert by_id["gas"]["amount_min"] == 40
    assert by_id["gas"]["amount_max"] == 70
    assert by_id["mobile_phone"]["amount_class"] == "fixed"
    assert all(e.get("enabled", True) for e in cat["essentials"])
    assert len(cat["essentials"]) == 11


def test_plain_english_variable_sentence_recent_regime():
    plan = build_plan("Electric", _electric_actuals_fixture(), as_of=date(2026, 9, 15))
    row = plan.ui_dict()
    assert "recent regime" in row["method"]
    sentence = plain_english_variable_sentence(row)
    assert "last 3 electric bills" in sentence
    assert "higher lately" in sentence
    assert "$280.55" in sentence
    assert "$181.56" in sentence
    assert "recent regime" not in sentence
    assert "med12" not in sentence
    detail = plain_english_variable_detail_lines(row)
    assert any("12-mo median" in line for line in detail)
    assert any("3-mo average" in line for line in detail)


def test_plain_english_variable_sentence_rule_amount_water():
    rules = [
        {
            "category": "Water",
            "amount": -95.00,
            "enabled": True,
            "start_date": "2026-01-01",
        },
        {
            "category": "Electric",
            "amount": -180.00,
            "enabled": True,
            "start_date": "2026-01-01",
        },
    ]
    # Minimal water actuals so last_actual populates
    water_actuals = [
        {
            "date": "2026-06-20",
            "amount": -161.97,
            "category": "Water",
            "label": "WATER",
            "source": "bank_csv",
            "enabled": True,
        },
        {
            "date": "2026-07-20",
            "amount": -120.00,
            "category": "Water",
            "label": "WATER",
            "source": "bank_csv",
            "enabled": True,
        },
        {
            "date": "2026-08-20",
            "amount": -139.77,
            "category": "Water",
            "label": "WATER",
            "source": "bank_csv",
            "enabled": True,
        },
    ]
    rows = variable_ui_rows(
        _electric_actuals_fixture() + water_actuals,
        rules,
        as_of=date(2026, 9, 15),
    )
    by_cat = {r["category"]: r for r in rows}
    water = by_cat["Water"]
    assert "rule amount" in water["method"]
    sentence = plain_english_variable_sentence(water)
    assert "$95.00" in sentence
    assert "left as-is" in sentence
    assert "rule amount" not in sentence
    assert "$139.77" in sentence


def test_gas_label_only_keeps_rule_amount():
    """Gas is variable class but label-only — expand_rules keeps -$45.00 (no REPLACE)."""
    from engine.variable_amounts import (
        VARIABLE_LABEL_ONLY_CATEGORIES,
        VARIABLE_OVERRIDE_CATEGORIES,
        VARIABLE_UI_CATEGORIES,
    )

    assert "Gas Bill" in VARIABLE_UI_CATEGORIES
    assert "Gas Bill" in VARIABLE_LABEL_ONLY_CATEGORIES
    assert "Gas Bill" not in VARIABLE_OVERRIDE_CATEGORIES
    assert "Electric" in VARIABLE_OVERRIDE_CATEGORIES
    assert "Water" in VARIABLE_LABEL_ONLY_CATEGORIES

    rules = [
        {
            "id": 5,
            "category": "Gas Bill",
            "label": "Gas Bill",
            "day_of_month": 28,
            "amount": -45.00,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    # Wild bank actuals must NOT override Gas (label-only)
    actuals = [
        {
            "date": f"2026-{m:02d}-28",
            "amount": -999.0,
            "category": "Gas Bill",
            "source": "bank_csv",
            "enabled": True,
        }
        for m in range(1, 13)
    ]
    flows = expand_rules(
        rules,
        date(2026, 10, 1),
        date(2026, 10, 31),
        actuals=actuals,
    )
    assert len(flows) == 1
    assert flows[0].date.day == 28
    assert abs(flows[0].amount - (-45.00)) < 1e-6


def test_gas_ui_row_and_plain_english():
    rules = [
        {
            "category": "Electric",
            "amount": -180.00,
            "enabled": True,
            "start_date": "2026-01-01",
        },
        {
            "category": "Water",
            "amount": -95.00,
            "enabled": True,
            "start_date": "2026-01-01",
        },
        {
            "category": "Gas Bill",
            "amount": -45.00,
            "enabled": True,
            "start_date": "2026-01-01",
        },
    ]
    gas_actuals = [
        {
            "date": "2026-06-28",
            "amount": -49.59,
            "category": "Gas Bill",
            "label": "DemoGasCo",
            "source": "bank_csv",
            "enabled": True,
        },
        {
            "date": "2026-07-28",
            "amount": -47.39,
            "category": "Gas Bill",
            "label": "DemoGasCo",
            "source": "bank_csv",
            "enabled": True,
        },
        {
            "date": "2026-08-26",
            "amount": -52.99,
            "category": "Gas Bill",
            "label": "DemoGasCo",
            "source": "bank_csv",
            "enabled": True,
        },
    ]
    rows = variable_ui_rows(
        _electric_actuals_fixture() + gas_actuals,
        rules,
        as_of=date(2026, 9, 15),
    )
    by_cat = {r["category"]: r for r in rows}
    assert set(by_cat) == {"Electric", "Water", "Gas Bill"}
    gas = by_cat["Gas Bill"]
    assert abs(float(gas["forecast"]) - 45.00) < 1e-6
    assert "rule amount" in gas["method"]
    sentence = plain_english_variable_sentence(gas)
    assert "$45.00" in sentence
    assert "Gas usage" in sentence or "gas" in sentence.lower()
    assert "left as-is" in sentence
    assert "rule amount" not in sentence
    assert "$52.99" in sentence
    # Electric still recent-regime / Water unchanged
    assert "recent regime" in by_cat["Electric"]["method"]
    assert "rule amount" in by_cat["Water"]["method"]


def test_gas_override_before_oct_unchanged_and_electric_water_untouched():
    """Gas label-only: apply_variable_override is a no-op; Electric still replaces Oct+."""
    gas_amt = apply_variable_override(
        "Gas Bill",
        date(2026, 10, 28),
        -45.00,
        actuals=[
            {
                "date": "2026-08-26",
                "amount": -999.0,
                "category": "Gas Bill",
                "source": "bank_csv",
                "enabled": True,
            }
        ]
        * 12,
    )
    assert abs(gas_amt - (-45.00)) < 1e-6

    electric_amt = apply_variable_override(
        "Electric",
        date(2026, 10, 3),
        -180.00,
        actuals=_electric_actuals_fixture(),
    )
    assert abs(electric_amt - (-251.966667)) < 0.01

    water_amt = apply_variable_override(
        "Water",
        date(2026, 10, 20),
        -95.00,
        actuals=[
            {
                "date": "2026-08-20",
                "amount": -999.0,
                "category": "Water",
                "source": "bank_csv",
                "enabled": True,
            }
        ]
        * 12,
    )
    assert abs(water_amt - (-95.00)) < 1e-6
