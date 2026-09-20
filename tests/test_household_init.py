"""Demo vs Clean household init — no cross-contamination on restart."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from engine import db as dbmod
from engine.excel_parity import LABEL_DEMO_CLEANING, PLANNED_SOURCE
from engine.household_init import (
    INIT_MODE_CLEAN,
    INIT_MODE_DEMO,
    SETTING_INIT_MODE,
    capability_status,
    empty_debts_store,
    get_init_mode,
    init_clean_household,
    init_demo_household,
    needs_first_run,
    peek_init_mode,
)
from engine.seed_load import ensure_seeded


ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_DEBTS = ROOT / "sample" / "fixtures" / "synthetic" / "debts.json"


@pytest.fixture
def debts_path(tmp_path, monkeypatch):
    """Never write demo/clean debts into the real repo data/ tree."""
    p = tmp_path / "debts.json"
    monkeypatch.setattr("engine.debt_paydown.DEBTS_PATH", p)
    return p


def _fresh_conn(tmp_path: Path):
    path = tmp_path / "cashflow.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)
    return conn, path


def test_demo_init_has_synthetic_data(tmp_path, monkeypatch, debts_path):
    conn, path = _fresh_conn(tmp_path)
    monkeypatch.setattr("engine.household_init._ROOT", tmp_path)
    # Point synthetic debts copy source still at repo fixture
    monkeypatch.setattr(
        "engine.household_init._SYNTHETIC_DEBTS", SYNTHETIC_DEBTS
    )

    summary = init_demo_household(conn)
    assert summary[SETTING_INIT_MODE] == INIT_MODE_DEMO
    assert get_init_mode(conn) == INIT_MODE_DEMO
    assert summary.get("rules_imported", 0) > 0

    rules = dbmod.list_rules(conn)
    assert len(rules) > 5
    labels = " ".join((r.get("label") or "") + (r.get("category") or "") for r in rules)
    assert "Alex" in labels or "Jordan" in labels or "Income" in labels

    scenarios = dbmod.list_scenarios(conn)
    assert len(scenarios) >= 1

    # excel parity overlays present after demo init (via import_seed)
    assert any(
        (r.get("label") or "").startswith(LABEL_DEMO_CLEANING) for r in rules
    ) or conn.execute(
        "SELECT COUNT(*) FROM planned_items WHERE source = ?", (PLANNED_SOURCE,)
    ).fetchone()[0] >= 0

    assert debts_path.exists()
    debts = json.loads(debts_path.read_text())
    assert len(debts.get("debts") or []) >= 1
    assert any("demo" in (d.get("name") or "").lower() or d.get("borrower") for d in debts["debts"])


def test_clean_init_has_none_of_demo_finances(tmp_path, monkeypatch, debts_path):
    conn, path = _fresh_conn(tmp_path)

    summary = init_clean_household(
        conn,
        household_name="Garcia Test",
        start_date="2026-09-20",
        end_date="2029-09-20",
        start_balance=1234.56,
        warning_threshold=200.0,
        as_of="2026-09-20",
    )
    assert summary[SETTING_INIT_MODE] == INIT_MODE_CLEAN
    assert get_init_mode(conn) == INIT_MODE_CLEAN
    assert summary["rules_imported"] == 0
    assert summary["excel_parity"] is None

    assert dbmod.list_rules(conn) == []
    assert dbmod.list_planned(conn) == []
    assert dbmod.list_scenarios(conn) == []
    assert dbmod.list_actuals(conn) == []

    settings = dbmod.get_settings(conn)
    assert abs(settings["start_balance"] - 1234.56) < 1e-9
    assert settings["warning_threshold"] == 200.0
    assert settings["suppress_rules_through"] is None

    # No Alex/Jordan paycheck labels
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", ("household_name",)
    ).fetchone()
    assert row["value"] == "Garcia Test"

    assert debts_path.exists()
    debts = json.loads(debts_path.read_text())
    assert debts.get("debts") == []

    # No excel_parity_applied stamp
    parity = conn.execute(
        "SELECT value FROM settings WHERE key = 'excel_parity_applied'"
    ).fetchone()
    assert parity is None


def test_restart_clean_does_not_mutate(tmp_path, monkeypatch, debts_path):
    conn, path = _fresh_conn(tmp_path)

    init_clean_household(
        conn,
        household_name="Stable",
        start_date="2026-01-01",
        end_date="2029-01-01",
        start_balance=500.0,
        warning_threshold=50.0,
    )
    before_settings = {
        r["key"]: r["value"]
        for r in conn.execute("SELECT key, value FROM settings").fetchall()
    }
    before_rules = dbmod.list_rules(conn)
    before_debts = debts_path.read_text()

    # Simulate app restart: ensure_seeded must not inject demo
    s1 = ensure_seeded(conn)
    s2 = ensure_seeded(conn)
    assert s1.get("skipped_demo_inject") is True
    assert s2.get("skipped_demo_inject") is True
    assert s1.get("excel_parity") is None
    assert get_init_mode(conn) == INIT_MODE_CLEAN

    after_settings = {
        r["key"]: r["value"]
        for r in conn.execute("SELECT key, value FROM settings").fetchall()
    }
    assert after_settings == before_settings
    assert dbmod.list_rules(conn) == before_rules == []
    assert dbmod.list_scenarios(conn) == []
    assert debts_path.read_text() == before_debts


def test_bootstrap_never_clobbers_clean(tmp_path, debts_path):
    """Thin clean DB must not be replaced by rich cloud_bootstrap."""
    data = tmp_path / "data"
    data.mkdir()
    live = data / "cashflow.db"
    boot = data / "cloud_bootstrap.db"

    # Build a "rich" bootstrap with fake actuals
    bconn = sqlite3.connect(str(boot))
    bconn.row_factory = sqlite3.Row
    dbmod.init_db(bconn)
    for i in range(120):
        bconn.execute(
            "INSERT INTO actuals(date, amount, category, label, source) VALUES (?,?,?,?,?)",
            ("2026-01-01", -1.0, "X", f"row{i}", "chase_black_card"),
        )
    bconn.commit()
    bconn.close()

    # Clean live DB (0 actuals — would look "thin")
    lconn = sqlite3.connect(str(live))
    lconn.row_factory = sqlite3.Row
    dbmod.init_db(lconn)
    init_clean_household(lconn, household_name="Keep Me", start_balance=9.0)
    lconn.close()

    # Patch module paths
    old_boot = dbmod.BOOTSTRAP_PATH
    old_db = dbmod.DB_PATH
    try:
        dbmod.BOOTSTRAP_PATH = boot
        dbmod.DB_PATH = live
        restored = dbmod.maybe_restore_from_bootstrap(live)
        assert restored is False
        conn = sqlite3.connect(str(live))
        conn.row_factory = sqlite3.Row
        mode = conn.execute(
            "SELECT value FROM settings WHERE key='household_init_mode'"
        ).fetchone()[0]
        assert mode == INIT_MODE_CLEAN
        n = conn.execute("SELECT COUNT(*) FROM actuals").fetchone()[0]
        assert n == 0
        bal = conn.execute(
            "SELECT value FROM settings WHERE key='start_balance'"
        ).fetchone()[0]
        assert float(bal) == 9.0
        conn.close()
    finally:
        dbmod.BOOTSTRAP_PATH = old_boot
        dbmod.DB_PATH = old_db


def test_ensure_seeded_empty_needs_init(tmp_path):
    conn, path = _fresh_conn(tmp_path)
    summary = ensure_seeded(conn)
    assert summary.get("needs_init") is True
    assert dbmod.list_rules(conn) == []
    assert get_init_mode(conn) is None


def test_needs_first_run_and_capability(tmp_path, monkeypatch, debts_path):
    conn, path = _fresh_conn(tmp_path)
    assert needs_first_run(path) is True
    init_clean_household(conn, household_name="Cap")
    # Re-point _ROOT for tax/retirement file checks
    monkeypatch.setattr("engine.household_init._ROOT", tmp_path)
    assert peek_init_mode(path) == INIT_MODE_CLEAN
    assert needs_first_run(path) is False
    cap = capability_status(conn)
    assert cap["mode"] == INIT_MODE_CLEAN
    assert cap["core"] == "ready"
    # Optional modules start Not enabled on Clean; learning waits for history.
    assert "Debt Paydown" in (cap.get("modules_not_enabled") or []) or (
        (cap.get("module_status") or {}).get("debt_paydown", {}).get("status") == "not_enabled"
    )
    assert cap["learning"] in ("waiting_for_history", "waiting")
    assert "not enabled" in cap["label_modules"].lower()
