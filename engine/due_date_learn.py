"""Learn recurring day-of-month from bank CSV / screenshot actuals.

CSV and screenshot transaction dates are the source of truth for WHEN bills
and income hit. Excel Data Input DOM is bootstrap only. Prefers due-date /
actual-post timing over accelerating payments.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from engine import db

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LEARNED_PATH = DATA / "due_date_learned.json"
PREFS_PATH = DATA / "payment_preferences.json"

DEFAULT_PREFS: dict[str, Any] = {
    "prefer_due_date_timing": True,
    "manual_pay": ["AT&T", "Water"],
    "auto_pay_default": True,
    "locked_dom": {"Home Mortgage": 11, "Jordan's Income": 8},
    "checklist_use_initiation_date": True,
    "note": "CSV/screenshot dates drive forecast; Excel DOM is bootstrap only.",
}

# Jordan's primary paycheck is ~$1500 early-month. BrightStart side_gig
# stamps (~$200–750, mid/late month) must not teach Jordan's Income DOM.
SECONDARY_INCOME_AMOUNT_TARGET = 1500.0
SECONDARY_INCOME_AMOUNT_TOLERANCE = 400.0

# Prefer bank_csv + recent pending itemizations as source of truth.
PREFERRED_SOURCES_PREFIXES = ("bank_csv", "pending_itemize_")
LOOKBACK_MONTHS_DEFAULT = 12
MIN_SAMPLES_DEFAULT = 3


def ensure_payment_preferences(path: Optional[Path] = None) -> dict[str, Any]:
    """Write default prefs if missing; merge any new default keys."""
    path = path or PREFS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    prefs = dict(DEFAULT_PREFS)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                prefs.update(existing)
        except (json.JSONDecodeError, OSError):
            pass
    # Locked DOM categories always present
    locked = dict(prefs.get("locked_dom") or {})
    locked.setdefault("Home Mortgage", 11)
    locked.setdefault("Jordan's Income", 8)
    prefs["locked_dom"] = locked
    prefs.setdefault("manual_pay", list(DEFAULT_PREFS["manual_pay"]))
    prefs.setdefault("prefer_due_date_timing", True)
    prefs.setdefault("auto_pay_default", True)
    prefs.setdefault("checklist_use_initiation_date", True)
    prefs.setdefault("note", DEFAULT_PREFS["note"])
    path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
    return prefs


def load_payment_preferences(path: Optional[Path] = None) -> dict[str, Any]:
    return ensure_payment_preferences(path)


def _is_preferred_source(source: Optional[str]) -> bool:
    s = (source or "").strip()
    if not s:
        return False
    return any(s == p or s.startswith(p) for p in PREFERRED_SOURCES_PREFIXES)


def _secondary_primary_paycheck_actual(row: dict) -> bool:
    """True if this Jordan's Income actual looks like the ~$1500 paycheck.

    Excludes BrightStart side_gig DIR DEP / PAYROLL stamps that are far from
    $1500 so they cannot pull learned DOM mid/late-month.
    """
    amt = float(row.get("amount") or 0)
    if abs(amt - SECONDARY_INCOME_AMOUNT_TARGET) > SECONDARY_INCOME_AMOUNT_TOLERANCE:
        return False
    label = (row.get("label") or "").upper()
    # BrightStart side-gig payroll is never the primary $1500 paycheck
    if "BRIGHTSTART" in label and ("PAYROLL" in label or "DIR DEP" in label):
        return False
    return True


def _filter_actuals_for_learning(category: str, rows: list[dict]) -> list[dict]:
    if category == "Jordan's Income":
        return [r for r in rows if _secondary_primary_paycheck_actual(r)]
    return rows


def _parse_iso(d: str | date) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def _mode_or_median(days: list[int]) -> int:
    if not days:
        raise ValueError("empty days")
    counts = Counter(days)
    top = counts.most_common()
    # Unique clear mode
    if len(top) == 1 or top[0][1] > top[1][1]:
        return int(top[0][0])
    # Tie → median of observed days
    return int(round(statistics.median(days)))


def _stdev(days: list[int]) -> float:
    if len(days) < 2:
        return 0.0
    return float(statistics.pstdev(days))


def _lookback_start(as_of: date, months: int) -> date:
    y, m = as_of.year, as_of.month
    m -= months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _primary_dom_per_month(
    rows: list[dict],
) -> list[dict[str, Any]]:
    """One observed DOM per year-month: day of largest |amount| txn."""
    by_ym: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = _parse_iso(r["date"])
        by_ym[f"{d.year:04d}-{d.month:02d}"].append(r)
    observed: list[dict[str, Any]] = []
    for ym in sorted(by_ym.keys()):
        items = by_ym[ym]
        best = max(items, key=lambda x: abs(float(x["amount"] or 0)))
        d = _parse_iso(best["date"])
        observed.append(
            {
                "year_month": ym,
                "dom": d.day,
                "date": d.isoformat(),
                "amount": float(best["amount"] or 0),
                "source": best.get("source"),
                "label": (best.get("label") or "")[:80],
            }
        )
    return observed


def _monthly_dom_categories(conn) -> dict[str, list[dict]]:
    """category → list of monthly_dom rules (enabled or not; we still learn)."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in db.list_rules(conn):
        if (r.get("cadence") or "monthly_dom") != "monthly_dom":
            continue
        if r.get("day_of_month") is None:
            continue
        by_cat[r["category"]].append(r)
    return dict(by_cat)


def compute_learned_stats(
    conn,
    *,
    lookback_months: int = LOOKBACK_MONTHS_DEFAULT,
    as_of: Optional[date] = None,
    min_samples: int = MIN_SAMPLES_DEFAULT,
) -> dict[str, Any]:
    """Compute per-category learned DOM stats from preferred actuals."""
    prefs = load_payment_preferences()
    locked = {str(k): int(v) for k, v in (prefs.get("locked_dom") or {}).items()}
    manual = set(prefs.get("manual_pay") or [])
    as_of = as_of or date.today()
    # Prefer project start_date if "today" is far from the twin's seam
    try:
        settings = db.get_settings(conn)
        seam = settings.get("start_date")
        if isinstance(seam, date) and abs((seam - as_of).days) > 60:
            as_of = seam
    except Exception:
        pass

    start = _lookback_start(as_of, lookback_months)
    actuals = [
        a
        for a in db.list_actuals(conn)
        if a.get("enabled", True)
        and _is_preferred_source(a.get("source"))
        and _parse_iso(a["date"]) >= start
        and _parse_iso(a["date"]) <= as_of + timedelta(days=3)  # allow near-future pending
    ]

    by_cat_rules = _monthly_dom_categories(conn)
    categories_out: dict[str, Any] = {}

    for category, rules in sorted(by_cat_rules.items()):
        cat_actuals = [a for a in actuals if (a.get("category") or "") == category]
        cat_actuals = _filter_actuals_for_learning(category, cat_actuals)
        observed = _primary_dom_per_month(cat_actuals)
        # Keep last lookback_months samples
        observed = observed[-lookback_months:]
        days = [o["dom"] for o in observed]
        current_doms = sorted({int(r["day_of_month"]) for r in rules if r.get("day_of_month") is not None})
        # Representative current = most common among enabled rules, else first
        enabled_doms = [
            int(r["day_of_month"])
            for r in rules
            if r.get("enabled") and r.get("day_of_month") is not None
        ]
        current_dom = (
            Counter(enabled_doms).most_common(1)[0][0]
            if enabled_doms
            else (current_doms[0] if current_doms else None)
        )

        locked_dom = locked.get(category)
        is_locked = locked_dom is not None
        n = len(days)
        confidence_ok = n >= min_samples

        if n:
            learned_raw = _mode_or_median(days)
            last_seen = observed[-1]["date"]
            spread = _stdev(days)
        else:
            learned_raw = None
            last_seen = None
            spread = None

        if is_locked:
            learned_dom = int(locked_dom)
            apply_eligible = False
            skip_reason = f"locked to day {locked_dom}"
        elif not confidence_ok:
            learned_dom = learned_raw
            apply_eligible = False
            skip_reason = f"low samples ({n} < {min_samples})"
        else:
            learned_dom = learned_raw
            apply_eligible = learned_dom is not None and current_dom is not None and int(learned_dom) != int(current_dom)
            skip_reason = None if apply_eligible or learned_dom == current_dom else "no change"

        pay_mode = "manual" if category in manual else ("auto" if prefs.get("auto_pay_default") else "unknown")

        categories_out[category] = {
            "category": category,
            "current_dom": current_dom,
            "current_doms": current_doms,
            "learned_dom": learned_dom,
            "learned_dom_raw": learned_raw,
            "observed_doms": days,
            "samples": n,
            "min_samples": min_samples,
            "confidence_ok": confidence_ok,
            "last_seen": last_seen,
            "stdev": round(spread, 2) if spread is not None else None,
            "locked": is_locked,
            "locked_dom": locked_dom,
            "pay_mode": pay_mode,
            "apply_eligible": bool(apply_eligible),
            "skip_reason": skip_reason,
            "rule_ids": [r["id"] for r in rules],
            "observed_detail": observed,
        }

    payload = {
        "as_of": as_of.isoformat(),
        "lookback_months": lookback_months,
        "min_samples": min_samples,
        "sources": list(PREFERRED_SOURCES_PREFIXES),
        "prefs_path": str(PREFS_PATH.relative_to(ROOT)) if PREFS_PATH.is_relative_to(ROOT) else str(PREFS_PATH),
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "categories": categories_out,
        "summary": {
            "n_categories": len(categories_out),
            "eligible_to_apply": sum(1 for c in categories_out.values() if c["apply_eligible"]),
            "locked": sum(1 for c in categories_out.values() if c["locked"]),
            "low_samples": sum(1 for c in categories_out.values() if not c["confidence_ok"] and not c["locked"]),
        },
    }
    return payload


def learn_from_actuals(
    conn,
    *,
    lookback_months: int = LOOKBACK_MONTHS_DEFAULT,
    as_of: Optional[date] = None,
    min_samples: int = MIN_SAMPLES_DEFAULT,
    out_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Refresh data/due_date_learned.json from DB actuals."""
    ensure_payment_preferences()
    payload = compute_learned_stats(
        conn,
        lookback_months=lookback_months,
        as_of=as_of,
        min_samples=min_samples,
    )
    path = out_path or LEARNED_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log.info(
        "due_date_learn: wrote %s (%s categories, %s eligible)",
        path,
        payload["summary"]["n_categories"],
        payload["summary"]["eligible_to_apply"],
    )
    return payload


def apply_learned_doms(
    conn,
    *,
    dry_run: bool = False,
    min_samples: int = MIN_SAMPLES_DEFAULT,
    learned: Optional[dict] = None,
) -> dict[str, Any]:
    """Update recurring_rules.day_of_month for monthly_dom when learned differs.

    Respects locked_dom (Home Mortgage → 11, Jordan's Income → 8). Skips categories with
    samples < min_samples. Returns a change report.
    """
    if learned is None:
        if LEARNED_PATH.exists():
            learned = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
        else:
            learned = learn_from_actuals(conn, min_samples=min_samples)

    prefs = load_payment_preferences()
    locked = {str(k): int(v) for k, v in (prefs.get("locked_dom") or {}).items()}

    changes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    cats = learned.get("categories") or {}
    for category, stats in cats.items():
        samples = int(stats.get("samples") or 0)
        learned_dom = stats.get("learned_dom")
        current_dom = stats.get("current_dom")
        rule_ids = stats.get("rule_ids") or []

        if category in locked:
            # Force lock on all Mortgage rules even if already 11
            lock_day = int(locked[category])
            for rid in rule_ids:
                row = conn.execute(
                    "SELECT id, day_of_month FROM recurring_rules WHERE id=?", (rid,)
                ).fetchone()
                if not row:
                    continue
                old = row["day_of_month"]
                if old != lock_day:
                    if not dry_run:
                        conn.execute(
                            "UPDATE recurring_rules SET day_of_month=? WHERE id=?",
                            (lock_day, rid),
                        )
                    changes.append(
                        {
                            "category": category,
                            "rule_id": rid,
                            "old": old,
                            "new": lock_day,
                            "samples": samples,
                            "reason": "locked_dom",
                        }
                    )
            skipped.append(
                {
                    "category": category,
                    "reason": f"locked to day {lock_day}",
                    "samples": samples,
                    "learned_raw": stats.get("learned_dom_raw"),
                    "current_dom": current_dom,
                }
            )
            continue

        if samples < min_samples:
            skipped.append(
                {
                    "category": category,
                    "reason": f"low samples ({samples} < {min_samples})",
                    "samples": samples,
                    "learned_dom": learned_dom,
                    "current_dom": current_dom,
                }
            )
            continue

        if learned_dom is None:
            skipped.append(
                {
                    "category": category,
                    "reason": "no learned_dom",
                    "samples": samples,
                    "current_dom": current_dom,
                }
            )
            continue

        learned_dom = int(learned_dom)
        any_change = False
        for rid in rule_ids:
            row = conn.execute(
                "SELECT id, day_of_month, cadence FROM recurring_rules WHERE id=?",
                (rid,),
            ).fetchone()
            if not row:
                continue
            if (row["cadence"] or "monthly_dom") != "monthly_dom":
                continue
            old = row["day_of_month"]
            if old == learned_dom:
                continue
            any_change = True
            if not dry_run:
                conn.execute(
                    "UPDATE recurring_rules SET day_of_month=? WHERE id=?",
                    (learned_dom, rid),
                )
            changes.append(
                {
                    "category": category,
                    "rule_id": rid,
                    "old": old,
                    "new": learned_dom,
                    "samples": samples,
                    "reason": "learned",
                }
            )
            log.info(
                "due_date_learn: %s rule %s DOM %s → %s (n=%s)",
                category,
                rid,
                old,
                learned_dom,
                samples,
            )

        if not any_change:
            skipped.append(
                {
                    "category": category,
                    "reason": "already matches learned",
                    "samples": samples,
                    "learned_dom": learned_dom,
                    "current_dom": current_dom,
                }
            )

    if not dry_run:
        conn.commit()

    report = {
        "dry_run": dry_run,
        "min_samples": min_samples,
        "changes": changes,
        "skipped": skipped,
        "n_changed_rules": len(changes),
        "n_categories_changed": len({c["category"] for c in changes if c.get("reason") == "learned"}),
    }
    return report


def clamp_dom(year: int, month: int, dom: int) -> date:
    last = monthrange(year, month)[1]
    return date(year, month, min(max(1, int(dom)), last))


def retarget_sep_planned(
    conn,
    *,
    learned: Optional[dict] = None,
    today: Optional[date] = None,
    source: str = "family_budget_sep2026_forecast",
    year: int = 2026,
    month: int = 9,
    max_me_delta: float = 1.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Retarget future planned items in the Sep forecast to learned DOMs.

    Skips locked categories, past dates, and aborts Sep date moves if month-end
    would shift by more than max_me_delta (keeps only Oct+ rule updates).
    """
    from engine.project import project

    today = today or date(2026, 9, 12)
    if learned is None:
        if LEARNED_PATH.exists():
            learned = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
        else:
            learned = learn_from_actuals(conn, as_of=today)

    prefs = load_payment_preferences()
    locked = set((prefs.get("locked_dom") or {}).keys())
    cats = learned.get("categories") or {}

    settings = db.get_settings(conn)
    rules = db.list_rules(conn)
    planned = db.list_planned(conn)
    actuals = db.list_actuals(conn)

    def _month_end() -> float:
        res = project(
            settings["start_date"],
            settings["end_date"],
            settings["start_balance"],
            db.list_rules(conn),
            db.list_planned(conn),
            db.list_actuals(conn),
            None,
            settings["warning_threshold"],
            suppress_rules_through=settings.get("suppress_rules_through"),
        )
        for m in res["months"]:
            if m["label"] == f"{year:04d}-{month:02d}":
                return float(m["month_end"])
        raise RuntimeError("month not found in projection")

    me_before = _month_end()

    proposals: list[dict[str, Any]] = []
    for p in planned:
        if (p.get("source") or "") != source:
            continue
        if not p.get("enabled", True):
            continue
        cat = p.get("category") or ""
        old_date = _parse_iso(p["date"])
        if old_date.year != year or old_date.month != month:
            continue
        if old_date <= today:
            continue
        if cat in locked:
            proposals.append(
                {
                    "id": p["id"],
                    "category": cat,
                    "old_date": old_date.isoformat(),
                    "action": "skip_locked",
                }
            )
            continue
        stats = cats.get(cat) or {}
        if not stats.get("confidence_ok"):
            proposals.append(
                {
                    "id": p["id"],
                    "category": cat,
                    "old_date": old_date.isoformat(),
                    "action": "skip_low_samples",
                    "samples": stats.get("samples"),
                }
            )
            continue
        learned_dom = stats.get("learned_dom")
        if learned_dom is None:
            continue
        new_date = clamp_dom(year, month, int(learned_dom))
        if new_date <= today:
            proposals.append(
                {
                    "id": p["id"],
                    "category": cat,
                    "old_date": old_date.isoformat(),
                    "new_date": new_date.isoformat(),
                    "action": "skip_would_be_past",
                }
            )
            continue
        if new_date == old_date:
            proposals.append(
                {
                    "id": p["id"],
                    "category": cat,
                    "old_date": old_date.isoformat(),
                    "action": "unchanged",
                }
            )
            continue
        proposals.append(
            {
                "id": p["id"],
                "category": cat,
                "old_date": old_date.isoformat(),
                "new_date": new_date.isoformat(),
                "learned_dom": int(learned_dom),
                "amount": float(p["amount"]),
                "action": "retarget",
            }
        )

    applied: list[dict[str, Any]] = []
    if not dry_run:
        for prop in proposals:
            if prop["action"] != "retarget":
                continue
            conn.execute(
                "UPDATE planned_items SET date=? WHERE id=?",
                (prop["new_date"], prop["id"]),
            )
            applied.append(prop)
        conn.commit()

        me_after = _month_end()
        if abs(me_after - me_before) > max_me_delta:
            # Revert Sep planned date moves
            for prop in applied:
                conn.execute(
                    "UPDATE planned_items SET date=? WHERE id=?",
                    (prop["old_date"], prop["id"]),
                )
            conn.commit()
            return {
                "me_before": me_before,
                "me_after_attempt": me_after,
                "me_after": _month_end(),
                "reverted": True,
                "reason": f"Sep month-end delta {me_after - me_before:.2f} > {max_me_delta}",
                "proposals": proposals,
                "applied": [],
            }

        # Sync forecast JSON dates when we applied moves
        _sync_forecast_json(source, applied)

        return {
            "me_before": me_before,
            "me_after": me_after,
            "reverted": False,
            "proposals": proposals,
            "applied": applied,
        }

    return {
        "me_before": me_before,
        "me_after": me_before,
        "reverted": False,
        "dry_run": True,
        "proposals": proposals,
        "applied": [],
    }


def _sync_forecast_json(source: str, applied: list[dict]) -> None:
    path = DATA / f"{source}.json"
    # family_budget file name matches source
    if source == "family_budget_sep2026_forecast":
        path = DATA / "family_budget_sep2026_forecast.json"
    if not path.exists() or not applied:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    items = data.get("items") or []
    by_key = {(a["category"], a["old_date"]): a for a in applied}
    for it in items:
        key = (it.get("category"), it.get("date"))
        if key in by_key:
            it["date"] = by_key[key]["new_date"]
            it["due_date_learned_retarget"] = True
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def proposed_shifts_table(learned: dict) -> list[dict[str, Any]]:
    """Compact report rows: category, old→new, samples."""
    rows = []
    for cat, s in (learned.get("categories") or {}).items():
        rows.append(
            {
                "category": cat,
                "old": s.get("current_dom"),
                "new": s.get("learned_dom"),
                "samples": s.get("samples"),
                "stdev": s.get("stdev"),
                "locked": s.get("locked"),
                "pay_mode": s.get("pay_mode"),
                "apply_eligible": s.get("apply_eligible"),
                "skip_reason": s.get("skip_reason"),
                "last_seen": s.get("last_seen"),
                "observed_doms": s.get("observed_doms"),
            }
        )
    return rows
