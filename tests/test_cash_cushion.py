"""Tests for red-month streak detection and cash-cushion math."""
from datetime import date

from engine.cash_cushion import (
    cash_cushion_amount,
    find_red_streaks,
    format_cushion_tip,
    primary_red_streak,
    round_up_cushion,
)


def _m(year, month, *, min_eod, month_end=None, days_negative=None, days_warning=0):
    neg = days_negative
    if neg is None:
        neg = 1 if min_eod < 0 else 0
    return {
        "year": year,
        "month": month,
        "label": f"{year}-{month:02d}",
        "min_eod": float(min_eod),
        "month_end": float(month_end if month_end is not None else min_eod),
        "days_negative": neg,
        "days_warning": days_warning,
        "first_breach": date(year, month, 15) if neg else None,
    }


def test_cash_cushion_from_deepest_trough():
    run = [
        _m(2027, 1, min_eod=-124.72, month_end=2600),
        _m(2027, 2, min_eod=-537.14, month_end=1900),
        _m(2027, 3, min_eod=-704.05, month_end=23000),
    ]
    assert abs(cash_cushion_amount(run) - 704.05) < 1e-9
    assert abs(cash_cushion_amount(run, clear_to=100.0) - 804.05) < 1e-9
    # Month-end signal would be wrong here (all positive) — stay on min_eod
    assert cash_cushion_amount(run, balance_key="month_end") == 0.0


def test_round_up_cushion():
    assert round_up_cushion(0) == 0.0
    assert round_up_cushion(-5) == 0.0
    assert round_up_cushion(704.05) == 705.0
    assert round_up_cushion(700.0) == 700.0
    assert round_up_cushion(704.05, step=10) == 710.0


def test_find_consecutive_streaks_across_year_boundary():
    months = [
        _m(2026, 11, min_eod=100.0),
        _m(2026, 12, min_eod=-50.0),
        _m(2027, 1, min_eod=-80.0),
        _m(2027, 2, min_eod=20.0),  # green break
        _m(2027, 6, min_eod=-10.0),
        _m(2027, 7, min_eod=-200.0),
        _m(2027, 8, min_eod=-5.0),
    ]
    streaks = find_red_streaks(months)
    assert len(streaks) == 2
    a, b = streaks
    assert (a["start_year"], a["start_month"]) == (2026, 12)
    assert (a["end_year"], a["end_month"]) == (2027, 1)
    assert a["length"] == 2
    assert a["start_month_name"] == "December"
    assert a["end_month_name"] == "January"
    assert abs(a["deepest_trough"] - (-80.0)) < 1e-9
    assert abs(a["cushion"] - 80.0) < 1e-9
    assert a["cushion_rounded"] == 80.0

    assert b["length"] == 3
    assert (b["start_year"], b["start_month"]) == (2027, 6)
    assert (b["end_year"], b["end_month"]) == (2027, 8)
    assert abs(b["deepest_trough"] - (-200.0)) < 1e-9
    assert b["cushion_rounded"] == 200.0


def test_primary_picks_longest_then_earliest():
    months = [
        _m(2026, 12, min_eod=-50.0),
        _m(2027, 1, min_eod=-80.0),
        _m(2027, 6, min_eod=-10.0),
        _m(2027, 7, min_eod=-200.0),
        _m(2027, 8, min_eod=-5.0),
    ]
    primary = primary_red_streak(months)
    assert primary is not None
    assert primary["length"] == 3
    assert primary["start_month_name"] == "June"
    assert "through August" in primary["plain_english"]
    assert "$200" in primary["plain_english"]


def test_primary_none_when_all_clear():
    months = [
        _m(2026, 11, min_eod=100.0),
        _m(2026, 12, min_eod=50.0),
    ]
    assert primary_red_streak(months) is None
    assert find_red_streaks(months) == []


def test_gap_in_calendar_breaks_streak_even_if_list_adjacent():
    """Missing intervening month must not glue two red months into one streak."""
    months = [
        _m(2027, 1, min_eod=-100.0),
        # February missing from list
        _m(2027, 3, min_eod=-50.0),
    ]
    streaks = find_red_streaks(months)
    assert len(streaks) == 2
    assert streaks[0]["length"] == 1
    assert streaks[1]["length"] == 1


def test_format_cushion_tip_single_and_multi():
    assert format_cushion_tip(
        start_month_name="January",
        end_month_name="January",
        length=1,
        cushion=125,
    ) == (
        "Set aside about $125 before January so checking doesn't go red in January"
    )
    assert format_cushion_tip(
        start_month_name="January",
        end_month_name="March",
        length=3,
        cushion=705,
    ) == (
        "Set aside about $705 before January so checking doesn't go red through March"
    )


def test_warning_key_uses_days_warning():
    months = [
        _m(2027, 1, min_eod=50.0, days_negative=0, days_warning=3),
        _m(2027, 2, min_eod=20.0, days_negative=0, days_warning=2),
    ]
    assert find_red_streaks(months, key="days_negative") == []
    streaks = find_red_streaks(months, key="days_warning", clear_to=100.0)
    assert len(streaks) == 1
    assert streaks[0]["length"] == 2
    # deepest min_eod is 20 → cushion to clear_to 100 = 80
    assert abs(streaks[0]["cushion"] - 80.0) < 1e-9
