"""Debt amortization tests against synthetic demo seed (Alex/Jordan household)."""
from datetime import date

from engine.debt_paydown import (
    compare_schedules,
    default_seed,
    get_debt,
    parse_lump_date,
    schedule_for_debt,
)


def _second():
    return get_debt(default_seed(), "mortgage_second")


def _first():
    return get_debt(default_seed(), "mortgage_first")


def _students():
    return get_debt(default_seed(), "student_loans")


def test_second_mortgage_baseline_payoff_synthetic():
    d = _second()
    sched = schedule_for_debt(d)
    assert sched.payoff_month == "2028-11"
    assert sched.rows[0].month == "2026-09"
    assert sched.rows[0].principal_extra == float(d.get("extra_principal_monthly") or 0)


def test_lump_sum_accelerates_second_mortgage():
    d = _second()
    baseline = schedule_for_debt(d)
    scenario = schedule_for_debt(d, lump_sum=10000.0, lump_month="2027-01")
    cmp = compare_schedules(baseline, scenario)
    assert scenario.payoff_month < baseline.payoff_month
    assert cmp["months_saved"] >= 1
    assert cmp["interest_saved"] > 0


def test_parse_lump_date():
    assert parse_lump_date("2027-01-01") == "2027-01"
    assert parse_lump_date(date(2027, 3, 1)) == "2027-03"


def test_first_mortgage_baseline_min_only():
    d = _first()
    sched = schedule_for_debt(d, extra_principal=0.0)
    assert sched.payoff_month == "2042-10"
    assert all(r.principal_extra == 0.0 for r in sched.rows)


def test_first_mortgage_extra_from_2028_accelerates():
    d = _first()
    baseline = schedule_for_debt(d, extra_principal=0.0)
    scenario = schedule_for_debt(d, extra_principal=2000.0, extra_start_month="2028-01")
    cmp = compare_schedules(baseline, scenario)
    assert scenario.payoff_month == "2034-01"
    assert cmp["months_saved"] and cmp["months_saved"] > 12
    first_extra = next(r for r in scenario.rows if r.principal_extra > 0)
    assert first_extra.month == "2028-01"


def test_student_loans_baseline_min_only():
    d = _students()
    sched = schedule_for_debt(d, extra_principal=0.0)
    assert sched.payoff_month == "2048-02"
    assert all(r.principal_extra == 0.0 for r in sched.rows)


def test_student_loans_extra_from_2028_accelerates():
    d = _students()
    baseline = schedule_for_debt(d, extra_principal=0.0)
    scenario = schedule_for_debt(d, extra_principal=2000.0, extra_start_month="2028-01")
    cmp = compare_schedules(baseline, scenario)
    assert scenario.payoff_month == "2031-04"
    assert cmp["months_saved"] and cmp["months_saved"] > 12
    assert scenario.payoff_month < baseline.payoff_month


def test_default_seed_is_synthetic_demo():
    store = default_seed()
    names = " ".join(d.get("name", "") + " " + d.get("servicer", "") for d in store["debts"]).lower()
    assert "demo" in names or "eduserve" in names or "home" in names
    assert ("nel"+"net") not in names
    assert ("roc"+"ket") not in names
    for d in store["debts"]:
        assert "DEMO" in str(d.get("account_number") or d.get("loan_number") or "DEMO")
