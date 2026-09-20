"""SQLite persistence for Household Cash Flow twin."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cashflow.db"
BOOTSTRAP_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_bootstrap.db"


def _count_actuals(db_file: Path, source: Optional[str] = None) -> int:
    if not db_file.exists():
        return 0
    try:
        c = sqlite3.connect(str(db_file))
        if source:
            n = c.execute(
                "SELECT COUNT(*) FROM actuals WHERE source = ?",
                (source,),
            ).fetchone()[0]
        else:
            n = c.execute("SELECT COUNT(*) FROM actuals").fetchone()[0]
        c.close()
        return int(n or 0)
    except sqlite3.Error:
        return 0


def _count_black_card(db_file: Path) -> int:
    return _count_actuals(db_file, "chase_black_card")


def _peek_init_mode(db_file: Path) -> Optional[str]:
    """Best-effort read of household_init_mode (avoid circular imports)."""
    if not db_file.exists():
        return None
    try:
        c = sqlite3.connect(str(db_file))
        try:
            row = c.execute(
                "SELECT value FROM settings WHERE key = 'household_init_mode'"
            ).fetchone()
            if row and row[0] in ("demo", "clean"):
                return str(row[0])
        finally:
            c.close()
    except sqlite3.Error:
        return None
    return None


def maybe_restore_from_bootstrap(
    db_path: Optional[Path] = None,
    *,
    allow_missing_copy: bool = False,
) -> bool:
    """Optionally seed cashflow.db from cloud_bootstrap.db (demo only).

    - **Never** overwrite a Clean Household DB (even if "thin").
    - Missing live DB: do **not** auto-copy unless ``allow_missing_copy``
      (Explore Demo / seed_demo). First-run UI chooses Demo vs Clean.
    - Existing demo/legacy thin Cloud DB vs rich bootstrap → replace once.

    Rule/catalog updates for demo still land via ``ensure_seeded`` +
    ``apply_excel_parity`` — not via this restore.
    """
    path = Path(db_path) if db_path else DB_PATH
    if not BOOTSTRAP_PATH.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and _peek_init_mode(path) == "clean":
        return False

    boot_n = _count_black_card(BOOTSTRAP_PATH)
    if not path.exists():
        if not allow_missing_copy:
            return False
        shutil.copy2(BOOTSTRAP_PATH, path)
        return True

    live_n = _count_black_card(path)
    live_all = _count_actuals(path)
    boot_all = _count_actuals(BOOTSTRAP_PATH)
    # Thin/empty Cloud DB from first deploy vs full local bootstrap (demo only)
    thin = (boot_n >= 100 and live_n < 50) or (boot_all >= 500 and live_all < 100)
    if thin and _peek_init_mode(path) != "clean":
        bak = path.with_suffix(".db.pre_bootstrap")
        try:
            shutil.copy2(path, bak)
        except OSError:
            pass
        shutil.copy2(BOOTSTRAP_PATH, path)
        return True
    return False


def connect(
    db_path: Optional[Path] = None,
    *,
    restore_bootstrap: bool = True,
    allow_missing_bootstrap_copy: bool = False,
) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    if restore_bootstrap:
        maybe_restore_from_bootstrap(
            path, allow_missing_copy=allow_missing_bootstrap_copy
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recurring_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            label TEXT,
            day_of_month INTEGER,
            amount REAL NOT NULL DEFAULT 0,
            amount_by_year TEXT,
            cadence TEXT NOT NULL DEFAULT 'monthly_dom',
            anchor_date TEXT,
            interval_days INTEGER DEFAULT 14,
            start_date TEXT,
            end_date TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS planned_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            label TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS actuals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            label TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            deltas TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS merchant_maps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL
        );
        """
    )
    conn.commit()
    _migrate(conn)



def _migrate(conn: sqlite3.Connection) -> None:
    """Additive schema upgrades (safe to re-run)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(actuals)").fetchall()}
    if "source" not in cols:
        conn.execute("ALTER TABLE actuals ADD COLUMN source TEXT")
    if "parent" not in cols:
        conn.execute("ALTER TABLE actuals ADD COLUMN parent TEXT")
    if "subcategory" not in cols:
        conn.execute("ALTER TABLE actuals ADD COLUMN subcategory TEXT")
    if "txn_type" not in cols:
        conn.execute("ALTER TABLE actuals ADD COLUMN txn_type TEXT")
    if "memo" not in cols:
        conn.execute("ALTER TABLE actuals ADD COLUMN memo TEXT")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(planned_items)").fetchall()}
    if "source" not in pcols:
        conn.execute("ALTER TABLE planned_items ADD COLUMN source TEXT")
    conn.commit()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_maps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL
        )
        """
    )
    mm_cols = {r[1] for r in conn.execute("PRAGMA table_info(merchant_maps)").fetchall()}
    if "parent" not in mm_cols:
        conn.execute("ALTER TABLE merchant_maps ADD COLUMN parent TEXT")
    if "subcategory" not in mm_cols:
        conn.execute("ALTER TABLE merchant_maps ADD COLUMN subcategory TEXT")
    conn.commit()


# ---- settings ----

DEFAULT_SETTINGS = {
    "start_date": "2026-09-12",
    "end_date": "2029-09-12",
    "start_balance": "5000.00",
    "warning_threshold": "100",
    "breach_threshold": "0",
    # When set (ISO date), recurring Data Input rules do not fire on/before this day.
    # Planned Budget workbook placements cover the current month instead.
    "suppress_rules_through": "2026-09-30",
}


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    suppress_raw = (s.get("suppress_rules_through") or "").strip()
    return {
        "start_date": date.fromisoformat(s["start_date"]),
        "end_date": date.fromisoformat(s["end_date"]),
        "start_balance": float(s["start_balance"]),
        "warning_threshold": float(s["warning_threshold"]),
        "breach_threshold": float(s["breach_threshold"]),
        "suppress_rules_through": date.fromisoformat(suppress_raw) if suppress_raw else None,
    }


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()


def save_settings(conn: sqlite3.Connection, settings: dict) -> None:
    suppress = settings.get("suppress_rules_through")
    if isinstance(suppress, date):
        suppress = suppress.isoformat()
    elif suppress is None:
        suppress = ""
    mapping = {
        "start_date": settings["start_date"].isoformat()
        if isinstance(settings["start_date"], date)
        else settings["start_date"],
        "end_date": settings["end_date"].isoformat()
        if isinstance(settings["end_date"], date)
        else settings["end_date"],
        "start_balance": settings["start_balance"],
        "warning_threshold": settings["warning_threshold"],
        "breach_threshold": settings.get("breach_threshold", 0),
        "suppress_rules_through": suppress,
    }
    for k, v in mapping.items():
        set_setting(conn, k, v)


# ---- rules ----

def list_rules(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM recurring_rules ORDER BY day_of_month, category").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        if d.get("amount_by_year"):
            d["amount_by_year"] = json.loads(d["amount_by_year"])
        else:
            d["amount_by_year"] = {}
        out.append(d)
    return out


def upsert_rule(conn: sqlite3.Connection, rule: dict) -> int:
    aby = rule.get("amount_by_year") or {}
    if isinstance(aby, dict):
        aby = json.dumps({str(k): v for k, v in aby.items()})
    fields = (
        rule.get("category"),
        rule.get("label") or rule.get("category"),
        rule.get("day_of_month"),
        float(rule.get("amount") or 0),
        aby,
        rule.get("cadence") or "monthly_dom",
        rule.get("anchor_date"),
        rule.get("interval_days") or 14,
        rule.get("start_date"),
        rule.get("end_date"),
        1 if rule.get("enabled", True) else 0,
    )
    if rule.get("id"):
        conn.execute(
            """UPDATE recurring_rules SET category=?, label=?, day_of_month=?, amount=?,
               amount_by_year=?, cadence=?, anchor_date=?, interval_days=?, start_date=?, end_date=?, enabled=?
               WHERE id=?""",
            (*fields, rule["id"]),
        )
        conn.commit()
        return int(rule["id"])
    cur = conn.execute(
        """INSERT INTO recurring_rules
           (category, label, day_of_month, amount, amount_by_year, cadence, anchor_date,
            interval_days, start_date, end_date, enabled)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        fields,
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM recurring_rules WHERE id=?", (rule_id,))
    conn.commit()


# ---- planned / actuals ----

def list_planned(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM planned_items ORDER BY date").fetchall()
    return [_item(r) for r in rows]


def list_actuals(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM actuals ORDER BY date").fetchall()
    return [_item(r) for r in rows]


def _item(r) -> dict:
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    return d


def add_planned(conn: sqlite3.Connection, item: dict) -> int:
    cur = conn.execute(
        "INSERT INTO planned_items(date, amount, category, label, enabled, source) VALUES (?,?,?,?,?,?)",
        (
            item["date"] if isinstance(item["date"], str) else item["date"].isoformat(),
            float(item["amount"]),
            item.get("category") or "Planned",
            item.get("label") or "",
            1 if item.get("enabled", True) else 0,
            item.get("source"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_planned(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM planned_items WHERE id=?", (item_id,))
    conn.commit()


def clear_planned_by_source(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute("DELETE FROM planned_items WHERE source=?", (source,))
    conn.commit()
    return int(cur.rowcount)


def add_actual(conn: sqlite3.Connection, item: dict) -> int:
    cur = conn.execute(
        """INSERT INTO actuals(date, amount, category, label, enabled, source, parent, subcategory, txn_type, memo)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            item["date"] if isinstance(item["date"], str) else item["date"].isoformat(),
            float(item["amount"]),
            item.get("category") or "Actual",
            item.get("label") or "",
            1 if item.get("enabled", True) else 0,
            item.get("source"),
            item.get("parent"),
            item.get("subcategory"),
            item.get("txn_type"),
            item.get("memo"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def clear_actuals_by_source(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute("DELETE FROM actuals WHERE source=?", (source,))
    conn.commit()
    return int(cur.rowcount)


def clear_all_actuals(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM actuals")
    conn.commit()
    return int(cur.rowcount)


def list_merchant_maps(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT id, pattern, category, parent, subcategory FROM merchant_maps
           ORDER BY length(pattern) DESC, id"""
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_merchant_map(
    conn: sqlite3.Connection,
    pattern: str,
    category: str,
    parent: str | None = None,
    subcategory: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO merchant_maps(pattern, category, parent, subcategory) VALUES (?,?,?,?)
           ON CONFLICT(pattern) DO UPDATE SET
             category=excluded.category,
             parent=COALESCE(excluded.parent, merchant_maps.parent),
             subcategory=COALESCE(excluded.subcategory, merchant_maps.subcategory)""",
        (pattern, category, parent, subcategory),
    )
    conn.commit()


def delete_merchant_map(conn: sqlite3.Connection, map_id: int) -> None:
    conn.execute("DELETE FROM merchant_maps WHERE id=?", (map_id,))
    conn.commit()


# ---- scenarios ----

def list_scenarios(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM scenarios ORDER BY id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["deltas"] = json.loads(d["deltas"] or "[]")
        out.append(d)
    return out


def get_scenario(conn: sqlite3.Connection, scenario_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["deltas"] = json.loads(d["deltas"] or "[]")
    return d


def save_scenario(conn: sqlite3.Connection, scenario: dict) -> int:
    deltas = scenario.get("deltas") or []
    deltas_json = json.dumps(deltas)
    if scenario.get("id"):
        conn.execute(
            """UPDATE scenarios SET name=?, description=?, deltas=?, updated_at=datetime('now')
               WHERE id=?""",
            (scenario["name"], scenario.get("description") or "", deltas_json, scenario["id"]),
        )
        conn.commit()
        return int(scenario["id"])
    cur = conn.execute(
        "INSERT INTO scenarios(name, description, deltas) VALUES (?,?,?)",
        (scenario["name"], scenario.get("description") or "", deltas_json),
    )
    conn.commit()
    return int(cur.lastrowid)


def duplicate_scenario(conn: sqlite3.Connection, scenario_id: int, new_name: Optional[str] = None) -> int:
    sc = get_scenario(conn, scenario_id)
    if not sc:
        raise ValueError(f"Scenario {scenario_id} not found")
    name = new_name or f"{sc['name']} (copy)"
    return save_scenario(
        conn,
        {"name": name, "description": sc.get("description") or "", "deltas": sc.get("deltas") or []},
    )


def delete_scenario(conn: sqlite3.Connection, scenario_id: int) -> None:
    conn.execute("DELETE FROM scenarios WHERE id=?", (scenario_id,))
    conn.commit()


def is_empty(conn: sqlite3.Connection) -> bool:
    n = conn.execute("SELECT COUNT(*) AS c FROM recurring_rules").fetchone()["c"]
    return n == 0
