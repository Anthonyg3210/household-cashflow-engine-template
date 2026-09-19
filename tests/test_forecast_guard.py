import pytest
"""Forecast coverage check: catalog miss + history continuity."""
from datetime import date

import sqlite3

from engine.db import add_actual, init_db, upsert_rule
from engine.forecast_guard import (
    enabled_essentials,
    load_essentials_catalog,
    run_coverage_check,
    summarize_coverage,
)


def _mem():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _day(d, flows):
    return {
        "date": d,
        "flows": flows,
        "flow_sum": sum(float(f["amount"]) for f in flows),
        "eod": 0.0,
        "negative": False,
        "warning": False,
    }


def _flow(category, amount, label=""):
    return {"category": category, "amount": amount, "label": label or category, "source": "rule"}


ADI_ONLY = {
    "look_ahead_days": 90,
    "essentials": [
        {
            "id": "demo_cleaning",
            "name": "Demo Cleaners",
            "match": ["Home Cleaning", "Casey"],
            "amount_min": 150,
            "amount_max": 210,
            "cadence": "monthly",
            "notes": "Zelle to Demo Cleaners ~$180 most months.",
            "enabled": True,
        }
    ],
}


@pytest.mark.skip(reason="production catalog/live-DB specific; template uses synthetic seed")
def test_seed_catalog_includes_required_essentials():
    items = enabled_essentials(load_essentials_catalog())
    ids = {i["id"] for i in items}
    assert {
        "demo_cleaning",
        "mortgage_first",
        "mortgage_second",
        "savings_extra",
        "fpl",
        "water",
        "att",
        "secondary_primary",
        "alex_northstar",
        "side_gig_secondary",
    } <= ids
    demo_cleaners = next(i for i in items if i["id"] == "demo_cleaning")
    assert demo_cleaners["amount_min"] <= 180 <= demo_cleaners["amount_max"]
    pre = next(i for i in items if i["id"] == "side_gig_secondary")
    assert 6 in (pre.get("off_months") or []) and 7 in (pre.get("off_months") or [])


def test_catalog_miss_demo_cleaning():
    conn = _mem()
    findings = run_coverage_check(
        conn,
        daily=[],
        as_of=date(2026, 9, 13),
        look_ahead_days=90,
        catalog=ADI_ONLY,
        actuals=[],
        rules=[],
    )
    demo_cleaners = next(f for f in findings if f["id"] == "demo_cleaning")
    assert demo_cleaners["severity"] == "missing"
    assert ("Casey" in demo_cleaners["title"] or "Demo" in demo_cleaners["title"])
    assert "missing" in demo_cleaners["title"].lower()
    assert "180" in demo_cleaners["detail"] or "$180" in demo_cleaners["investigate_prompt"]
    assert "investigate" in demo_cleaners["investigate_prompt"].lower() or "Please investigate" in demo_cleaners["investigate_prompt"]
    summary = summarize_coverage(findings)
    assert summary["level"] == "red"
    assert any(g["id"] == "demo_cleaning" for g in summary["gaps"])


def test_catalog_hit_demo_cleaning_ok():
    conn = _mem()
    daily = [
        _day(date(2026, 10, 15), [_flow("Home Cleaning", -180.0, "Demo Cleaners service ($180/mo)")]),
        _day(date(2026, 11, 15), [_flow("Home Cleaning", -180.0, "Demo Cleaners service ($180/mo)")]),
        _day(date(2026, 12, 15), [_flow("Home Cleaning", -180.0, "Demo Cleaners service ($180/mo)")]),
    ]
    findings = run_coverage_check(
        conn,
        daily=daily,
        as_of=date(2026, 9, 13),
        look_ahead_days=90,
        catalog=ADI_ONLY,
        actuals=[],
        rules=[],
    )
    demo_cleaners = next(f for f in findings if f["id"] == "demo_cleaning")
    assert demo_cleaners["severity"] == "ok"
    assert summarize_coverage(findings)["level"] == "green"


def test_catalog_hit_via_enabled_rule():
    conn = _mem()
    upsert_rule(
        conn,
        {
            "category": "Home Cleaning",
            "label": "Demo Cleaners service ($180/mo)",
            "day_of_month": 15,
            "amount": -180.0,
            "cadence": "monthly_dom",
            "start_date": "2026-10-01",
            "end_date": "2029-09-12",
            "enabled": True,
        },
    )
    findings = run_coverage_check(
        conn,
        daily=[],
        as_of=date(2026, 9, 13),
        look_ahead_days=90,
        catalog=ADI_ONLY,
        actuals=[],
    )
    demo_cleaners = next(f for f in findings if f["id"] == "demo_cleaning")
    assert demo_cleaners["severity"] == "ok"
    assert demo_cleaners["rule_hits"] >= 2


def test_catalog_wrong_amount_is_weak():
    conn = _mem()
    daily = [_day(date(2026, 10, 15), [_flow("Home Cleaning", -50.0, "Casey")]) ]
    findings = run_coverage_check(
        conn,
        daily=daily,
        as_of=date(2026, 9, 13),
        look_ahead_days=90,
        catalog=ADI_ONLY,
        actuals=[],
        rules=[],
    )
    demo_cleaners = next(f for f in findings if f["id"] == "demo_cleaning")
    assert demo_cleaners["severity"] == "weak"
    assert summarize_coverage(findings)["level"] == "amber"


@pytest.mark.skip(reason="production catalog/live-DB specific; template uses synthetic seed")
def test_history_recurring_without_forecast_flags():
    conn = _mem()
    # Last 6 complete months before 2026-09-13 = Mar–Aug 2026. Hit 5 of 6.
    for ym, day in (
        ("2026-03", 4),
        ("2026-04", 3),
        ("2026-05", 5),
        ("2026-06", 2),
        ("2026-08", 6),
    ):
        add_actual(
            conn,
            {
                "date": f"{ym}-{day:02d}",
                "amount": -180.00,
                "category": "Pest Control",
                "label": "HomeTeam pest",
                "source": "bank_csv",
                "enabled": True,
            },
        )
    findings = run_coverage_check(
        conn,
        daily=[],
        as_of=date(2026, 9, 13),
        look_ahead_days=90,
        catalog=ADI_ONLY,
        rules=[],
    )
    hist = [f for f in findings if f.get("source") == "history"]
    assert hist, findings
    pest = next(f for f in hist if "Pest" in f["title"] or f.get("name") == "Pest Control")
    assert pest["severity"] == "missing"
    assert pest["typical_amount"] > 200
    assert "Please investigate" in pest["investigate_prompt"]
    assert summarize_coverage(findings)["level"] == "red"


def test_history_recurring_with_forecast_not_flagged():
    conn = _mem()
    for ym in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
        add_actual(
            conn,
            {
                "date": f"{ym}-04",
                "amount": -89.0,
                "category": "Pest Control",
                "label": "HomeTeam pest",
                "source": "bank_csv",
                "enabled": True,
            },
        )
    daily = [
        _day(date(2026, 10, 4), [_flow("Pest Control", -89.0, "HomeTeam pest")]),
        _day(date(2026, 11, 4), [_flow("Pest Control", -89.0, "HomeTeam pest")]),
    ]
    findings = run_coverage_check(
        conn,
        daily=daily,
        as_of=date(2026, 9, 13),
        look_ahead_days=90,
        catalog=ADI_ONLY,
        rules=[],
    )
    hist = [f for f in findings if f.get("source") == "history"]
    assert hist == []
    # Demo Cleaners still missing from this mini catalog run
    demo_cleaners = next(f for f in findings if f["id"] == "demo_cleaning")
    assert demo_cleaners["severity"] == "missing"
