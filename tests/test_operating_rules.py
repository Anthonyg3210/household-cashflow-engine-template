"""Generic operating rules. Synthetic amounts only."""
from __future__ import annotations

from datetime import date
from io import StringIO

from engine.bank_import import parse_csv_rows
from engine.debt_paydown import schedule_for_debt
from engine.ledger_rules import (
    card_owed_once,
    collapse_same_visit_pending,
    is_pending_card_status,
    is_unverified_feed,
    posted_card_actuals_from_pending_header,
    relabel_changes_cash,
    resolve_forecast_dom,
    source_updates_account,
)
from engine.project import project
from engine.variable_amounts import apply_variable_override, build_plan, plain_english_variable_sentence


def test_locked_post_day_ignores_lender_next_payment_label():
    assert resolve_forecast_dom(locked_day=15, posted_days=[1, 1, 1], lender_next_day=1) == 15
    assert resolve_forecast_dom(posted_days=[3, 18, 3], lender_next_day=1) == 3
    assert resolve_forecast_dom(lender_next_day=1) is None


def test_schedule_uses_payment_day_not_next_payment_date():
    sched = schedule_for_debt(
        {
            "current_balance": 100.0,
            "annual_rate": 0.0,
            "regular_payment": 200.0,
            "payment_day": 15,
            "next_payment_date": "2026-10-01",
            "projection": {"mode": "full", "first_month": "2026-10"},
            "extra_principal_monthly": 0.0,
        }
    )
    assert sched.payoff_date == date(2026, 10, 15)


def test_variable_month_uses_posted_amount_not_average():
    rows = []
    for ym, amt in {
        "2025-11": -100.0,
        "2025-12": -100.0,
        "2026-01": -100.0,
        "2026-02": -100.0,
        "2026-03": -100.0,
        "2026-04": -100.0,
        "2026-05": -100.0,
        "2026-06": -100.0,
        "2026-07": -100.0,
        "2026-08": -100.0,
        "2026-09": -100.0,
        "2026-10": -40.0,
    }.items():
        rows.append(
            {
                "date": f"{ym}-04",
                "amount": amt,
                "category": "FPL",
                "label": "Utility bill",
                "source": "bank_csv",
                "enabled": True,
            }
        )
    plan = build_plan("FPL", rows, as_of=date(2026, 10, 15))
    posted, method = plan.amount_for(date(2026, 10, 4))
    assert method == "posted actual"
    assert abs(posted - 40.0) < 1e-9
    later, later_method = plan.amount_for(date(2026, 11, 4))
    assert later_method != "posted actual"
    assert abs(later - 40.0) > 1.0
    replaced = apply_variable_override("FPL", date(2026, 10, 4), -100.0, plans={"FPL": plan})
    assert abs(replaced - (-40.0)) < 1e-9
    sentence = plain_english_variable_sentence(plan.ui_dict())
    assert "posted bank amount" in sentence


def test_forecast_line_replaced_when_bank_day_and_amount_differ():
    rules = [
        {
            "id": 1,
            "category": "Rent",
            "label": "Rent",
            "day_of_month": 5,
            "amount": -100.0,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    actuals = [
        {
            "date": "2026-09-09",
            "amount": -80.0,
            "category": "Rent",
            "label": "Rent",
            "source": "bank_csv",
        }
    ]
    res = project(date(2026, 9, 1), date(2026, 9, 30), 500.0, rules, actuals=actuals)
    flows = [f for day in res["daily"] for f in day["flows"]]
    rent = [f for f in flows if f.category == "Rent"]
    assert len(rent) == 1
    assert rent[0].date == date(2026, 9, 9)
    assert abs(rent[0].amount - (-80.0)) < 1e-9
    assert rent[0].source == "actual"


def test_relabel_replaces_month_line_without_changing_other_cash():
    rules = [
        {
            "id": 1,
            "category": "Utilities",
            "label": "City Power",
            "day_of_month": 4,
            "amount": -90.0,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    actuals = [
        {
            "date": "2026-09-06",
            "amount": -75.0,
            "category": "Home",
            "label": "City Power",
            "source": "statement",
        }
    ]
    res = project(date(2026, 9, 1), date(2026, 9, 30), 500.0, rules, actuals=actuals)
    flows = [f for day in res["daily"] for f in day["flows"]]
    assert len(flows) == 1
    assert flows[0].category == "Home"
    assert abs(flows[0].amount - (-75.0)) < 1e-9
    assert relabel_changes_cash(-90.0, -90.0) is False
    assert relabel_changes_cash(-90.0, -75.0) is True


def test_biweekly_actual_does_not_wipe_the_other_paycheck():
    rules = [
        {
            "id": 1,
            "category": "Pay",
            "label": "Pay",
            "cadence": "biweekly",
            "anchor_date": "2026-09-04",
            "interval_days": 14,
            "amount": 200.0,
            "enabled": True,
        }
    ]
    actuals = [
        {
            "date": "2026-09-04",
            "amount": 210.0,
            "category": "Pay",
            "label": "Pay",
            "source": "bank_csv",
        }
    ]
    res = project(date(2026, 9, 1), date(2026, 9, 30), 0.0, rules, actuals=actuals)
    flows = [f for day in res["daily"] for f in day["flows"]]
    pays = sorted(flows, key=lambda f: f.date)
    assert [f.date for f in pays] == [date(2026, 9, 4), date(2026, 9, 18)]
    assert abs(pays[0].amount - 210.0) < 1e-9
    assert pays[0].source == "actual"
    assert abs(pays[1].amount - 200.0) < 1e-9
    assert pays[1].source == "rule"


def test_observed_feed_is_not_promoted_into_forecast():
    rules = [
        {
            "id": 1,
            "category": "Rent",
            "label": "Rent",
            "day_of_month": 5,
            "amount": -100.0,
            "cadence": "monthly_dom",
            "enabled": True,
        }
    ]
    actuals = [
        {
            "date": "2026-09-05",
            "amount": -999.0,
            "category": "Rent",
            "label": "Rent",
            "source": "observed:feed",
        }
    ]
    res = project(date(2026, 9, 1), date(2026, 9, 30), 500.0, rules, actuals=actuals)
    flows = [f for day in res["daily"] for f in day["flows"]]
    assert len(flows) == 1
    assert abs(flows[0].amount - (-100.0)) < 1e-9
    assert flows[0].source == "rule"
    assert is_unverified_feed("observed")
    assert is_unverified_feed("plaid:item")
    assert not is_unverified_feed("bank_csv")
    assert not is_unverified_feed("statement")
    assert not is_unverified_feed("")


def test_card_pending_counted_once_and_same_visit_not_stacked():
    # Limit 1000, available 700 → owed 300. Current 250 omits pending. Do not add pending again.
    owed = card_owed_once(limit=1000, available=700, posted=250, pending=50, current=250)
    assert abs(owed - 300) < 1e-9
    # No limit/available: posted + pending once, not pending twice.
    owed_b = card_owed_once(posted=250, pending=50, current=250)
    assert abs(owed_b - 300) < 1e-9
    visit = collapse_same_visit_pending(
        [
            {"visit_id": "v1", "role": "pre_tip", "desc": "Cafe", "amount": -20},
            {"visit_id": "v1", "role": "tip_final", "desc": "Cafe", "amount": -24},
            {"visit_id": "v1", "role": "stale_pending", "desc": "Cafe", "amount": -20},
            {"visit_id": "v2", "role": "pending", "desc": "Market", "amount": -8},
        ]
    )
    assert len(visit) == 2
    cafe = next(i for i in visit if i["visit_id"] == "v1")
    assert cafe["role"] == "tip_final"
    assert cafe["amount"] == -24
    assert posted_card_actuals_from_pending_header(48.0) == []


def test_pending_card_row_is_not_a_posted_actual():
    raw = StringIO(
        "Transaction Date,Description,Type,Amount,Status\n"
        "10/02/2026,Cafe Example,Sale,-20.00,Pending\n"
        "10/04/2026,Market Example,Sale,-12.00,Posted\n"
    )
    rows = parse_csv_rows(raw)
    assert [r["label"] for r in rows] == ["Cafe Example", "Market Example"]
    assert is_pending_card_status(rows[0]["status"])
    assert not is_pending_card_status(rows[1]["status"])
    assert source_updates_account("checking", "Checking")
    assert not source_updates_account("checking", "card")
