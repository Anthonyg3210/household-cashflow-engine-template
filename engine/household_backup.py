"""Whole-household backup ZIP + restore (validate, auto-backup current)."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from engine import db

_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _ROOT / "data"
BACKUPS_DIR = DATA_DIR / "backups"

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"
DB_ARCNAME = "cashflow.db"

# Sidecar JSON/JSONL under data/ — included when present.
SIDECAR_NAMES = (
    "debts.json",
    "live_checking.json",
    "merchant_map.json",
    "net_worth_snapshot.json",
    "retirement_plan.json",
    "retirement_accounts_private.json",
    "retirement_snapshot.json",
    "retirement_history.jsonl",
    "tax_profile.json",
    "tax_history.jsonl",
    "plan_features.json",
    "rewards_cards.json",
    "black_card_import_meta.json",
    "black_card_snapshot.json",
    "black_card_budget_context.json",
    "due_date_learned.json",
    "payment_preferences.json",
    "taxonomy_v2.json",
)

REQUIRED_TABLES = (
    "settings",
    "recurring_rules",
    "planned_items",
    "actuals",
    "scenarios",
    "merchant_maps",
)


def _utc_stamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backups_dir(root: Optional[Path] = None) -> Path:
    base = Path(root) if root else _ROOT
    d = base / "data" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in REQUIRED_TABLES:
        try:
            out[t] = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
        except sqlite3.Error:
            out[t] = -1
    return out


def _sidecar_paths(data_dir: Path) -> list[Path]:
    found = []
    for name in SIDECAR_NAMES:
        p = data_dir / name
        if p.is_file():
            found.append(p)
    return found


def create_household_backup(
    *,
    root: Optional[Path] = None,
    db_path: Optional[Path] = None,
    dest_dir: Optional[Path] = None,
    label: str = "manual",
) -> dict[str, Any]:
    """Write a timestamped ZIP of DB + present sidecars. Returns report."""
    root = Path(root) if root else _ROOT
    data_dir = root / "data"
    db_file = Path(db_path) if db_path else data_dir / "cashflow.db"
    out_dir = Path(dest_dir) if dest_dir else backups_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = _utc_stamp()
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "manual"))[:40]
    zip_path = out_dir / f"household_backup_{stamp}_{safe_label}.zip"

    if not db_file.exists():
        raise FileNotFoundError(f"No database at {db_file}")

    # Snapshot DB via SQLite backup API so we don't copy a hot WAL inconsistently.
    snap = out_dir / f".snap_{stamp}.db"
    src = sqlite3.connect(str(db_file))
    try:
        dst = sqlite3.connect(str(snap))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    sidecars = _sidecar_paths(data_dir)
    counts: dict[str, int] = {}
    init_mode = None
    try:
        c = sqlite3.connect(str(snap))
        c.row_factory = sqlite3.Row
        try:
            db.init_db(c)
            counts = _table_counts(c)
            row = c.execute(
                "SELECT value FROM settings WHERE key = 'household_init_mode'"
            ).fetchone()
            init_mode = row[0] if row else None
        finally:
            c.close()
    except sqlite3.Error:
        counts = {}

    manifest = {
        "version": MANIFEST_VERSION,
        "created_at": stamp,
        "label": label,
        "init_mode": init_mode,
        "db_file": DB_ARCNAME,
        "table_counts": counts,
        "sidecars": [p.name for p in sidecars],
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")
        zf.write(snap, arcname=DB_ARCNAME)
        for p in sidecars:
            zf.write(p, arcname=f"sidecar/{p.name}")

    try:
        snap.unlink(missing_ok=True)
    except OSError:
        pass

    return {
        "path": str(zip_path),
        "created_at": stamp,
        "label": label,
        "table_counts": counts,
        "sidecars": [p.name for p in sidecars],
        "init_mode": init_mode,
        "bytes": zip_path.stat().st_size if zip_path.exists() else 0,
    }


def validate_backup_zip(zip_path: Path | str) -> dict[str, Any]:
    """Validate ZIP structure without applying. Raises ValueError on hard fail."""
    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"Backup not found: {path}")
    issues: list[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        if MANIFEST_NAME not in names:
            raise ValueError("Backup missing manifest.json")
        if DB_ARCNAME not in names:
            raise ValueError("Backup missing cashflow.db")
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid manifest.json: {e}") from e
        if int(manifest.get("version") or 0) < 1:
            issues.append("manifest version missing or unsupported")

        # Smoke-check DB tables inside the zip
        with tempfile.TemporaryDirectory() as td:
            tmp_db = Path(td) / "check.db"
            with zf.open(DB_ARCNAME) as src, open(tmp_db, "wb") as dst:
                shutil.copyfileobj(src, dst)
            conn = sqlite3.connect(str(tmp_db))
            try:
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                missing = [t for t in REQUIRED_TABLES if t not in tables]
                if missing:
                    raise ValueError(f"Backup DB missing tables: {', '.join(missing)}")
                counts = _table_counts(conn)
            finally:
                conn.close()

        sidecar_listed = list(manifest.get("sidecars") or [])
        for name in sidecar_listed:
            arc = f"sidecar/{name}"
            if arc not in names:
                issues.append(f"manifest lists sidecar {name} but file missing in zip")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "manifest": manifest,
        "table_counts": counts,
        "path": str(path),
    }


def restore_household_backup(
    zip_path: Path | str,
    *,
    root: Optional[Path] = None,
    db_path: Optional[Path] = None,
    auto_backup_current: bool = True,
) -> dict[str, Any]:
    """Validate ZIP, auto-backup current household, then replace DB + sidecars."""
    root = Path(root) if root else _ROOT
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    live_db = Path(db_path) if db_path else data_dir / "cashflow.db"

    validation = validate_backup_zip(zip_path)
    if not validation["ok"] and validation.get("issues"):
        # Soft issues only — hard fails already raised
        pass

    pre_backup = None
    if auto_backup_current and live_db.exists():
        pre_backup = create_household_backup(
            root=root,
            db_path=live_db,
            dest_dir=backups_dir(root),
            label="pre_restore",
        )

    path = Path(zip_path)
    restored_sidecars: list[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            zf.extract(DB_ARCNAME, path=td_path)
            extracted_db = td_path / DB_ARCNAME
            # Replace live DB
            if live_db.exists():
                live_db.unlink()
            for suffix in ("-wal", "-shm"):
                side = Path(str(live_db) + suffix)
                if side.exists():
                    side.unlink()
            shutil.copy2(extracted_db, live_db)

            # Restore sidecars listed in zip
            for info in zf.infolist():
                if not info.filename.startswith("sidecar/") or info.is_dir():
                    continue
                name = Path(info.filename).name
                if not name or name not in SIDECAR_NAMES:
                    continue
                dest = data_dir / name
                with zf.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                restored_sidecars.append(name)

    # Confirm restored DB opens
    conn = sqlite3.connect(str(live_db))
    try:
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        counts = _table_counts(conn)
    finally:
        conn.close()

    return {
        "ok": True,
        "restored_db": str(live_db),
        "restored_sidecars": restored_sidecars,
        "table_counts": counts,
        "pre_restore_backup": pre_backup,
        "validation": validation,
    }
