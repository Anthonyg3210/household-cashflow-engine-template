"""Optional module flags + capability status + clean never injects demo modules."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import db as dbmod
from engine.household_init import (
    INIT_MODE_CLEAN,
    INIT_MODE_DEMO,
    capability_status,
    init_clean_household,
    init_demo_household,
)
from engine.module_flags import (
    default_flags,
    is_module_enabled,
    load_module_flags,
    module_status_map,
    nav_pages_for_flags,
    set_module_enabled,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    c = dbmod.connect(db_path)
    dbmod.init_db(c)
    debts = tmp_path / "debts.json"
    monkeypatch.setattr("engine.debt_paydown.DEBTS_PATH", debts)
    monkeypatch.setattr("engine.module_flags._ROOT", tmp_path)
    monkeypatch.setattr(
        "engine.module_flags._CLEAN_WIPE_SIDECARS",
        (
            tmp_path / "data" / "tax_profile.json",
            tmp_path / "data" / "retirement_plan.json",
            tmp_path / "data" / "net_worth_snapshot.json",
            tmp_path / "data" / "black_card_snapshot.json",
        ),
    )
    (tmp_path / "data").mkdir(exist_ok=True)
    return c, tmp_path, debts


def test_clean_defaults_modules_off_and_wipes_sidecars(conn):
    c, root, debts = conn
    (root / "data" / "tax_profile.json").write_text('{"demo": true}', encoding="utf-8")
    (root / "data" / "retirement_plan.json").write_text('{"demo": true}', encoding="utf-8")
    (root / "data" / "net_worth_snapshot.json").write_text("{}", encoding="utf-8")

    init_clean_household(c, household_name="Portable")
    flags = load_module_flags(c)
    assert flags == default_flags(demo=False)
    assert all(v is False for v in flags.values())
    assert not (root / "data" / "tax_profile.json").exists()
    assert not (root / "data" / "retirement_plan.json").exists()
    assert debts.exists()
    assert json.loads(debts.read_text())["debts"] == []

    cap = capability_status(c)
    assert cap["mode"] == INIT_MODE_CLEAN
    assert cap["core"] == "ready"
    assert "not enabled" in cap["label_modules"].lower()
    assert cap["learning"] == "waiting_for_history"
    status = module_status_map(c)
    assert status["debt_paydown"]["status"] == "not_enabled"
    assert status["learning"]["status"] == "waiting_for_history"


def test_demo_enables_optional_modules(conn, monkeypatch):
    c, root, debts = conn
    from engine.seed_load import resolve_seed_dir

    if resolve_seed_dir() is None:
        pytest.skip("no synthetic seed")
    # Point synthetic debts copy at repo fixture if present
    repo = Path(__file__).resolve().parent.parent
    candidates = [
        repo / "sample" / "fixtures" / "synthetic" / "debts.json",
        repo / "seed" / "debts.json",
    ]
    for cand in candidates:
        if cand.exists():
            monkeypatch.setattr("engine.household_init._SYNTHETIC_DEBTS", cand)
            break
    init_demo_household(c)
    flags = load_module_flags(c)
    assert all(flags.values()), flags
    pages = nav_pages_for_flags(flags)
    assert "Household debt paydown" in pages
    assert "Enable Debt Paydown" not in pages
    assert capability_status(c)["mode"] == INIT_MODE_DEMO


def test_toggle_module_and_nav(conn):
    c, root, debts = conn
    init_clean_household(c)
    pages = nav_pages_for_flags(load_module_flags(c))
    assert "Enable Debt Paydown" in pages
    set_module_enabled(c, "debt_paydown", True)
    assert is_module_enabled(c, "debt_paydown")
    pages2 = nav_pages_for_flags(load_module_flags(c))
    assert "Household debt paydown" in pages2
    assert "Enable Debt Paydown" not in pages2
    st = module_status_map(c)["debt_paydown"]
    assert st["status"] == "needs_setup"
    assert st["status_label"] == "Needs setup"


def test_learning_ready_after_history(conn):
    c, root, debts = conn
    init_clean_household(c)
    for i in range(5):
        c.execute(
            "INSERT INTO actuals(date, amount, category, label, source) VALUES (?,?,?,?,?)",
            (f"2026-01-{i+1:02d}", -10.0, "Coffee", f"t{i}", "bank_csv"),
        )
    c.commit()
    st = module_status_map(c)["learning"]
    assert st["status"] == "ready"
    assert capability_status(c)["learning"] == "ready"
