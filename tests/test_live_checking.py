"""Tests for durable live-checking note sync."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.live_checking import (
    check_live_checking_consistency,
    set_live_checking,
)


def _settings(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key LIKE 'live_checking%'"
    ).fetchall()
    conn.close()
    return {k: v for k, v in rows}


def test_set_live_checking_writes_json_and_both_dbs(tmp_path: Path):
    pending = [{"desc": "POS DEBIT CURSOR", "amount": -40.2, "status": "pending"}]
    payload = set_live_checking(
        2785.99,
        "2026-09-15",
        pending=pending,
        source="unit_test",
        prior_available=2826.19,
        root=tmp_path,
    )

    json_path = tmp_path / "data" / "live_checking.json"
    assert json_path.exists()
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    assert raw["balance"] == 2785.99
    assert raw["as_of"] == "2026-09-15"
    assert raw["label"] == "TOTAL CHECKING (...8538)"
    assert "2785.99" in raw["as_of_note"].replace(",", "").replace("$", "")
    assert "Pending already reduces available." in raw["as_of_note"]
    assert "POS DEBIT CURSOR" in raw["as_of_note"]
    assert raw["source"] == "unit_test"
    assert raw["prior_available"] == 2826.19
    assert raw["pending"] == pending
    assert payload["as_of_note"] == raw["as_of_note"]

    for db_name in ("cashflow.db", "cloud_bootstrap.db"):
        s = _settings(tmp_path / "data" / db_name)
        assert s["live_checking_balance"] == "2785.99"
        assert s["live_checking_as_of"] == "2026-09-15"
        assert s["live_checking_label"] == "TOTAL CHECKING (...8538)"
        assert s["live_checking_note"] == raw["as_of_note"]

    assert check_live_checking_consistency(root=tmp_path) == []


def test_set_live_checking_explicit_note(tmp_path: Path):
    note = "Custom note with $1,234.56 inside"
    set_live_checking(1234.56, "2026-09-16", note=note, root=tmp_path)
    raw = json.loads((tmp_path / "data" / "live_checking.json").read_text())
    assert raw["as_of_note"] == note
    assert _settings(tmp_path / "data" / "cashflow.db")["live_checking_note"] == note
    assert check_live_checking_consistency(root=tmp_path) == []


def test_check_consistency_detects_stale_note_and_mismatch(tmp_path: Path):
    set_live_checking(2785.99, "2026-09-15", root=tmp_path)
    # Stale note on bootstrap only
    conn = sqlite3.connect(str(tmp_path / "data" / "cloud_bootstrap.db"))
    conn.execute(
        "UPDATE settings SET value=? WHERE key='live_checking_note'",
        ("Chase available $2,856.19 as of 2026-09-14 (stale)",),
    )
    conn.commit()
    conn.close()
    issues = check_live_checking_consistency(root=tmp_path)
    assert any("cloud_bootstrap.db" in i and "note" in i for i in issues)

    # Balance mismatch on cashflow
    conn = sqlite3.connect(str(tmp_path / "data" / "cashflow.db"))
    conn.execute(
        "UPDATE settings SET value=? WHERE key='live_checking_balance'",
        ("9999.00",),
    )
    conn.commit()
    conn.close()
    issues = check_live_checking_consistency(root=tmp_path)
    assert any("cashflow.db" in i and "balance" in i for i in issues)


def test_repo_live_checking_consistency_empty():
    """Template has no committed live balances; consistency is N/A until user adds data."""
    from pathlib import Path
    from engine.live_checking import _json_path
    if not _json_path().exists():
        import pytest
        pytest.skip("no data/live_checking.json in template (expected)")
    assert check_live_checking_consistency() == []
