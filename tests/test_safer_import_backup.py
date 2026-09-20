"""Safer bank CSV import (preview/merge/replace/dupes) + household backup round-trip."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from engine import db as dbmod
from engine.bank_import import (
    CSV_SOURCE,
    import_csv,
    preview_csv_import,
    txn_fingerprint,
)
from engine.household_backup import (
    create_household_backup,
    restore_household_backup,
    validate_backup_zip,
)
from engine.household_init import (
    INIT_MODE_CLEAN,
    get_init_mode,
    init_clean_household,
)


def _fresh(tmp_path: Path):
    path = tmp_path / "cashflow.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)
    return conn, path


def _write_checking_csv(path: Path, rows: list[tuple], *, with_id: bool = False) -> Path:
    """rows: (posting_date, description, amount[, txn_id])."""
    if with_id:
        lines = ["Details,Posting Date,Description,Amount,Type,Balance,Transaction ID"]
        for r in rows:
            date, desc, amt, tid = r
            lines.append(f"DEBIT,{date},{desc},{amt},ACH,,{tid}")
    else:
        lines = ["Details,Posting Date,Description,Amount,Type,Balance"]
        for r in rows:
            date, desc, amt = r[:3]
            lines.append(f"DEBIT,{date},{desc},{amt},ACH,")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_fingerprint_prefers_stable_id():
    a = txn_fingerprint(
        date="2026-09-01",
        amount=-12.34,
        label="PUBLIX #1",
        source=CSV_SOURCE,
        external_id="ABC123",
    )
    b = txn_fingerprint(
        date="2026-09-99",
        amount=0,
        label="OTHER",
        source=CSV_SOURCE,
        external_id="ABC123",
    )
    assert a == b == f"id:{CSV_SOURCE}:ABC123"
    c = txn_fingerprint(
        date="2026-09-01",
        amount=-12.34,
        label="PUBLIX #1",
        memo="",
        source=CSV_SOURCE,
    )
    assert c.startswith(f"{CSV_SOURCE}|2026-09-01|-12.34|")


def test_preview_then_merge_skips_duplicates(tmp_path):
    conn, db_path = _fresh(tmp_path)
    csv1 = _write_checking_csv(
        tmp_path / "a.csv",
        [
            ("09/01/2026", "PUBLIX STORE", -50.00),
            ("09/02/2026", "SHELL OIL", -40.00),
        ],
    )
    r1 = import_csv(
        conn, csv1, mode="merge", confirm_replace=False, create_backup=False, root=tmp_path
    )
    assert r1["rows_imported"] == 2
    assert r1["mode"] == "merge"

    prev = preview_csv_import(conn, csv1)
    assert prev["rows_parsed"] == 2
    assert prev["duplicate_count"] == 2
    assert prev["new_row_count"] == 0
    assert prev["short_history_warning"] is True

    csv2 = _write_checking_csv(
        tmp_path / "b.csv",
        [
            ("09/01/2026", "PUBLIX STORE", -50.00),  # dupe
            ("09/03/2026", "TARGET", -25.00),  # new
        ],
    )
    r2 = import_csv(
        conn, csv2, mode="merge", create_backup=False, root=tmp_path
    )
    assert r2["rows_imported"] == 1
    assert r2["rows_skipped_duplicates"] == 1
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM actuals WHERE source=?", (CSV_SOURCE,)
    ).fetchone()["c"]
    assert n == 3


def test_merge_stable_id_dedupe(tmp_path):
    conn, _ = _fresh(tmp_path)
    csv1 = _write_checking_csv(
        tmp_path / "id1.csv",
        [("09/01/2026", "PUBLIX", -10.00, "TXN-1")],
        with_id=True,
    )
    import_csv(conn, csv1, mode="merge", create_backup=False, root=tmp_path)
    # Same ID, different date/amount — still a duplicate
    csv2 = _write_checking_csv(
        tmp_path / "id2.csv",
        [("09/15/2026", "OTHER MERCHANT", -999.00, "TXN-1")],
        with_id=True,
    )
    r = import_csv(conn, csv2, mode="merge", create_backup=False, root=tmp_path)
    assert r["rows_imported"] == 0
    assert r["rows_skipped_duplicates"] == 1


def test_replace_requires_confirm_and_backs_up(tmp_path, monkeypatch):
    conn, db_path = _fresh(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Point live db into tmp data dir for backup sidecar layout
    live = data_dir / "cashflow.db"
    live.write_bytes(db_path.read_bytes())
    conn.close()
    conn = sqlite3.connect(str(live))
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)

    csv1 = _write_checking_csv(
        tmp_path / "r1.csv",
        [("09/01/2026", "PUBLIX", -10.00), ("09/02/2026", "SHELL", -20.00)],
    )
    import_csv(conn, csv1, mode="merge", create_backup=False, root=tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM actuals").fetchone()[0] == 2

    csv2 = _write_checking_csv(
        tmp_path / "r2.csv",
        [("09/10/2026", "TARGET", -5.00)],
    )
    with pytest.raises(ValueError, match="confirm_replace"):
        import_csv(conn, csv2, mode="replace", confirm_replace=False, root=tmp_path)

    report = import_csv(
        conn,
        csv2,
        mode="replace",
        confirm_replace=True,
        create_backup=True,
        root=tmp_path,
    )
    assert report["mode"] == "replace"
    assert report["rows_imported"] == 1
    assert report["rows_cleared"] == 2
    assert (report.get("backup") or {}).get("path")
    bak = Path(report["backup"]["path"])
    assert bak.exists()
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM actuals WHERE source=?", (CSV_SOURCE,)
    ).fetchone()["c"]
    assert n == 1
    # Change report present
    assert report["change_report"]["inserted"] == 1
    assert report["change_report"]["cleared_bank_csv"] == 2


def test_preview_overlap_and_short_history(tmp_path):
    conn, _ = _fresh(tmp_path)
    csv1 = _write_checking_csv(
        tmp_path / "hist.csv",
        [
            ("08/01/2026", "PUBLIX", -10.00),
            ("08/20/2026", "SHELL", -20.00),
        ],
    )
    import_csv(conn, csv1, mode="merge", create_backup=False, root=tmp_path)
    csv2 = _write_checking_csv(
        tmp_path / "overlap.csv",
        [
            ("08/15/2026", "TARGET", -5.00),
            ("08/25/2026", "COSTCO", -30.00),
        ],
    )
    prev = preview_csv_import(conn, csv2)
    assert prev["overlap"] is True
    assert prev["short_history_warning"] is True
    assert prev["duplicate_count"] == 0
    assert prev["new_row_count"] == 2


def test_backup_clean_restore_roundtrip(tmp_path, monkeypatch):
    root = tmp_path
    data = root / "data"
    data.mkdir()
    db_path = data / "cashflow.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)

    monkeypatch.setattr("engine.debt_paydown.DEBTS_PATH", data / "debts.json")
    init_clean_household(
        conn,
        household_name="Roundtrip HH",
        start_date="2026-09-20",
        end_date="2029-09-20",
        start_balance=777.0,
    )
    dbmod.add_actual(
        conn,
        {
            "date": "2026-09-01",
            "amount": -12.0,
            "category": "Publix",
            "label": "PUBLIX",
            "source": CSV_SOURCE,
            "parent": "Groceries",
            "subcategory": "Publix",
        },
    )
    (data / "live_checking.json").write_text(
        json.dumps({"balance": 777.0, "as_of": "2026-09-20", "as_of_note": "777.0"}),
        encoding="utf-8",
    )
    (data / "debts.json").write_text(
        json.dumps({"as_of": None, "debts": [{"name": "Demo Loan", "balance": 100}]}),
        encoding="utf-8",
    )
    conn.commit()

    bak = create_household_backup(root=root, db_path=db_path, label="roundtrip")
    zip_path = Path(bak["path"])
    assert zip_path.exists()
    val = validate_backup_zip(zip_path)
    assert val["ok"] is True
    assert "live_checking.json" in bak["sidecars"]
    assert "debts.json" in bak["sidecars"]

    # Wipe to clean empty household
    conn.close()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)
    init_clean_household(conn, household_name="", start_balance=0.0)
    assert conn.execute("SELECT COUNT(*) FROM actuals").fetchone()[0] == 0
    conn.close()

    result = restore_household_backup(
        zip_path, root=root, db_path=db_path, auto_backup_current=True
    )
    assert result["ok"] is True
    assert result.get("pre_restore_backup")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    assert get_init_mode(conn) == INIT_MODE_CLEAN
    settings = dbmod.get_settings(conn)
    assert float(settings["start_balance"]) == 777.0
    name = conn.execute(
        "SELECT value FROM settings WHERE key='household_name'"
    ).fetchone()["value"]
    assert name == "Roundtrip HH"
    assert conn.execute("SELECT COUNT(*) FROM actuals").fetchone()[0] == 1
    live = json.loads((data / "live_checking.json").read_text())
    assert live["balance"] == 777.0
    debts = json.loads((data / "debts.json").read_text())
    assert len(debts["debts"]) == 1
    conn.close()


def test_legacy_replace_bool_still_works(tmp_path):
    """Back-compat: replace_csv_actuals=True without mode auto-confirms."""
    conn, _ = _fresh(tmp_path)
    csv1 = _write_checking_csv(
        tmp_path / "leg.csv",
        [("09/01/2026", "PUBLIX", -10.00)],
    )
    r = import_csv(conn, csv1, replace_csv_actuals=True, create_backup=False, root=tmp_path)
    assert r["mode"] == "replace"
    assert r["rows_imported"] == 1
