"""Tests for retirement nest-egg and age-aware Retirement OS math."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.retirement import (
    AGE_AWARE_SWR,
    DEFAULT_COMFORT_ANNUAL,
    HEALTHCARE_TEMP_ADDER_ANNUAL,
    average_monthly_outflow,
    build_age_tile,
    build_month_totals_from_checklists,
    build_snapshot,
    classic_25x,
    current_retirement_assets,
    default_plan,
    derive_lifestyle_need_annual,
    evaluate_age_bracket,
    evaluate_brackets,
    evaluate_lifestyle_tiles,
    flex_nest_egg,
    income_replacement_annual,
    load_plan,
    load_retirement_accounts,
    load_snapshot,
    nest_egg_for_age,
    nest_egg_target,
    project_portfolio,
    required_monthly_contribution,
    save_plan,
    swr_for_age,
    taxable_bridge_months,
    warehouse_status,
    years_until,
    format_money,
    format_money_compact,
    format_pct,
    format_years,
    format_months,
)


def test_nest_egg_25x_at_4_percent():
    assert nest_egg_target(100_000, 0.04) == pytest.approx(2_500_000)
    assert nest_egg_target(120_000, 0.04) == pytest.approx(3_000_000)


def test_nest_egg_3_5_percent_preset():
    assert nest_egg_target(100_000, 0.035) == pytest.approx(100_000 / 0.035)


def test_nest_egg_rejects_nonpositive_rate():
    with pytest.raises(ValueError):
        nest_egg_target(100_000, 0.0)


def test_age_aware_swr_midpoints():
    assert swr_for_age(50) == pytest.approx(0.034)
    assert swr_for_age(55) == pytest.approx(0.036)
    assert swr_for_age(60) == pytest.approx(0.039)
    # Multipliers ≈ 29.4× / 27.8× / 25.6×
    assert (1 / swr_for_age(50)) == pytest.approx(29.4117647, rel=1e-6)
    assert (1 / swr_for_age(55)) == pytest.approx(27.7777778, rel=1e-6)
    assert (1 / swr_for_age(60)) == pytest.approx(25.6410256, rel=1e-6)
    with pytest.raises(ValueError):
        swr_for_age(52)


def test_age_aware_nest_egg_never_one_target():
    """Same Comfort need ⇒ three different nest eggs by age."""
    need = DEFAULT_COMFORT_ANNUAL
    n50 = nest_egg_for_age(need, 50)
    n55 = nest_egg_for_age(need, 55)
    n60 = nest_egg_for_age(need, 60)
    assert n50 == pytest.approx(need / 0.034)
    assert n55 == pytest.approx(need / 0.036)
    assert n60 == pytest.approx(need / 0.039)
    assert n50 > n55 > n60
    # Classic 25× is footnote only — matches flex at age 50 (3.4+0.6=4.0)
    assert classic_25x(need) == pytest.approx(need / 0.04)
    assert flex_nest_egg(need, 50) == pytest.approx(classic_25x(need))


def test_pmt_extra_mo_closes_comfort_gap():
    """Extra $/mo at 5% real FV-matches the Comfort gap."""
    need_floor = DEFAULT_COMFORT_ANNUAL * 0.8
    tile = build_age_tile(
        retire_age=50,
        current_age=40,
        floor_annual=need_floor,
        comfort_annual=DEFAULT_COMFORT_ANNUAL,
        life_annual=DEFAULT_COMFORT_ANNUAL * 1.2,
        current_assets=527_756.81,
        real_return=0.05,
    )
    assert tile.swr_rigid == pytest.approx(0.034)
    assert tile.gap_comfort > 0
    assert tile.extra_mo > 0
    r = 0.05 / 12
    n = 120
    fv = tile.extra_mo * (((1 + r) ** n) - 1) / r
    assert fv == pytest.approx(tile.gap_comfort, rel=1e-6)

    # Age 55 / 60 also produce positive PMT with seeded assets
    tiles = evaluate_lifestyle_tiles(
        current_age=40,
        floor_annual=need_floor,
        comfort_annual=DEFAULT_COMFORT_ANNUAL,
        life_annual=DEFAULT_COMFORT_ANNUAL * 1.2,
        current_assets=527_756.81,
    )
    by_age = {t.retire_age: t for t in tiles}
    assert by_age[50].extra_mo == pytest.approx(13_977.42, rel=1e-3)
    assert by_age[55].extra_mo == pytest.approx(6_601.84, rel=1e-3)
    assert by_age[60].extra_mo == pytest.approx(3_020.03, rel=1e-3)


def test_years_until_and_project_portfolio():
    assert years_until(40, 50) == 10
    assert years_until(40, 55) == 15
    assert years_until(40, 60) == 20
    assert project_portfolio(100_000, 10, 0.05) == pytest.approx(100_000 * (1.05**10))
    assert project_portfolio(100_000, 0, 0.05) == pytest.approx(100_000)


def test_gap_surplus_and_monthly_contribution():
    bracket = evaluate_age_bracket(
        retire_age=60,
        current_age=40,
        annual_lifestyle_need=100_000,
        current_assets=2_000_000,
        withdrawal_rate=0.04,
        real_return=0.05,
    )
    assert bracket.nest_egg_needed == pytest.approx(2_500_000)
    assert bracket.projected_assets > 2_500_000
    assert bracket.on_track is True
    assert bracket.surplus > 0
    assert bracket.monthly_contribution_to_close == pytest.approx(0.0)

    short = evaluate_age_bracket(
        retire_age=50,
        current_age=40,
        annual_lifestyle_need=100_000,
        current_assets=100_000,
        withdrawal_rate=None,  # age-aware 3.4%
        real_return=0.05,
    )
    assert short.swr == pytest.approx(0.034)
    assert short.on_track is False
    assert short.gap > 0
    assert short.monthly_contribution_to_close > 0
    r = 0.05 / 12
    n = 120
    fv = short.monthly_contribution_to_close * (((1 + r) ** n) - 1) / r
    assert fv == pytest.approx(short.gap, rel=1e-6)


def test_zero_return_monthly_is_linear():
    gap = 120_000.0
    monthly = required_monthly_contribution(gap, years=10, annual_real_return=0.0)
    assert monthly == pytest.approx(1_000.0)


@pytest.mark.skip(reason="requires production live DB / personal snapshots; not in privacy template")
def test_seeded_accounts_total_includes_brokeragelink():
    assets = current_retirement_assets()
    assert assets["brokeragelink"] == pytest.approx(515_916.24)
    assert assets["individual"] == pytest.approx(11_840.57)
    assert assets["total"] == pytest.approx(527_756.81)
    assert assets["show_brokeragelink_on_dashboard"] is False


def test_load_plan_has_age_40():
    plan = load_plan()
    assert plan["person"]["age_years"] == 40
    assert plan["assumptions"]["real_return"] == 0.05
    assert AGE_AWARE_SWR[50] == 0.034


def test_save_and_reload_plan(tmp_path: Path):
    p = tmp_path / "retirement_plan.json"
    plan = default_plan()
    plan["lifestyle_need"]["annual_override"] = 110_000.0
    plan["custom_retire_age"] = 52
    save_plan(plan, p)
    loaded = load_plan(p)
    assert loaded["lifestyle_need"]["annual_override"] == 110_000.0
    assert loaded["custom_retire_age"] == 52
    assert loaded["person"]["name"] == "Alex Rivera"


@pytest.mark.skip(reason="requires production live DB / personal snapshots; not in privacy template")
def test_derive_lifestyle_excludes_debt_extras():
    months = [
        {
            "money_out": 12_000.0,
            "by_category": {
                "Home Mortgage": 2450.00,
                "Savings": 3500.0,
                "Student Loans": 650.00,
                "Groceries": 4931.98,
            },
        },
        {
            "money_out": 12_000.0,
            "by_category": {
                "Home Mortgage": 2450.00,
                "Savings": 3500.0,
                "Student Loans": 650.00,
                "Groceries": 4931.98,
            },
        },
    ]
    need = derive_lifestyle_need_annual(
        month_totals=months,
        exclude_debt_payoff_extras=True,
        assume_high_interest_debt_paid=True,
        housing_budget_mode="keep_housing",
    )
    assert need["monthly"] == pytest.approx(7803.07)
    assert need["annual"] == pytest.approx(7803.07 * 12)
    assert need["source"] == "twin_avg_expenses"
    assert "Savings" in need["excluded_categories"]
    assert "Student Loans" in need["excluded_categories"]


def test_derive_lifestyle_falls_back_to_temporary_comfort():
    need = derive_lifestyle_need_annual(month_totals=None, income_based_annual=None)
    assert need["annual"] == pytest.approx(DEFAULT_COMFORT_ANNUAL)
    assert need["source"] == "temporary_twin"


def test_derive_lifestyle_override_wins():
    need = derive_lifestyle_need_annual(
        month_totals=[{"money_out": 9999.0, "by_category": {}}],
        annual_override=96_000.0,
    )
    assert need["annual"] == 96_000.0
    assert need["source"] == "override"


def test_income_replacement_and_brackets_custom_age():
    plan = default_plan()
    ann = income_replacement_annual(plan)
    assert ann == pytest.approx(117123.76 + 18_000.0)
    results = evaluate_brackets(
        current_age=40,
        annual_lifestyle_need=100_000,
        current_assets=500_000,
        withdrawal_rate=0.04,
        custom_age=52,
    )
    ages = [r.retire_age for r in results]
    assert ages == [50, 55, 60, 52]


@pytest.mark.skip(reason="requires production live DB / personal snapshots; not in privacy template")
def test_build_month_totals_from_checklists():
    checklists = [
        [
            {"category": "Alex's Income", "amount": 4200.00},
            {"category": "Savings", "amount": -3500.0},
            {"category": "Home Mortgage", "amount": -2450.00},
        ]
    ]
    totals = build_month_totals_from_checklists(checklists)
    assert totals[0]["money_out"] == pytest.approx(6371.09)
    assert totals[0]["by_category"]["Savings"] == pytest.approx(3500.0)


def test_average_monthly_outflow_plain():
    assert average_monthly_outflow(
        [{"money_out": 10_000}, {"money_out": 12_000}]
    ) == pytest.approx(11_000)


@pytest.mark.skip(reason="requires production live DB / personal snapshots; not in privacy template")
def test_accounts_file_keeps_brokeragelink_off_dashboard():
    acc = load_retirement_accounts()
    bl = acc.get("brokeragelink") or {}
    assert bl.get("show_on_dashboard") is False
    assert float(bl.get("balance")) == pytest.approx(515_916.24)


def test_taxable_bridge_and_warehouse_banner():
    months = taxable_bridge_months(11_840.57, DEFAULT_COMFORT_ANNUAL)
    assert months == pytest.approx(1.4, abs=0.05)
    wh = warehouse_status()
    assert wh["learning_live"] is False
    assert "Warehouse empty" in wh["banner"] or "headers" in wh["status"]


def test_healthcare_adder_raises_comfort_nest_egg():
    tile = build_age_tile(
        retire_age=55,
        current_age=40,
        floor_annual=DEFAULT_COMFORT_ANNUAL * 0.8,
        comfort_annual=DEFAULT_COMFORT_ANNUAL,
        life_annual=DEFAULT_COMFORT_ANNUAL * 1.2,
        current_assets=527_756.81,
        healthcare_adder_annual=HEALTHCARE_TEMP_ADDER_ANNUAL,
    )
    assert tile.comfort_with_healthcare > tile.comfort
    assert tile.comfort_with_healthcare == pytest.approx(
        (DEFAULT_COMFORT_ANNUAL + 24_000) / 0.036
    )


@pytest.mark.skip(reason="requires production live DB / personal snapshots; not in privacy template")
def test_seeded_snapshot_loads():
    snap = load_snapshot()
    assert snap is not None
    assert snap["spend"]["comfort_annual"] == pytest.approx(103_023.61)
    assert snap["targets"]["50"]["swr_rigid"] == pytest.approx(0.034)
    assert snap["classic_25x_comfort"] == pytest.approx(2_575_590.25)
    built = build_snapshot()
    assert built["targets"]["55"]["comfort"] == pytest.approx(
        snap["targets"]["55"]["comfort"], rel=1e-4
    )


def test_display_formatters_do_not_change_math():
    """UI formatters only — never alter nest-egg / SWR results."""
    assert format_money(2_575_590.25) == "$2,575,590.25"
    assert format_money_compact(2_861_766.94) == "$2.86M"
    assert format_money_compact(859_660.23) == "$859,660.23"
    assert format_pct(0.034) == "3.40%"
    assert format_years(15) == "15 yrs"
    assert format_months(1.379) == "1.4 mo"
    # math untouched
    assert nest_egg_for_age(DEFAULT_COMFORT_ANNUAL, 55) == pytest.approx(
        DEFAULT_COMFORT_ANNUAL / 0.036
    )
