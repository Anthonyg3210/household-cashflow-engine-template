"""General breach mitigation analyzer (Excel-style month overrides).

For any red period:
  1. Find first negative EOD + contributing outflows.
  2. Classify each outflow: fixed | flexible | income_timing | unknown.
  3. Propose typed solutions and simulate clear-red impact.
  4. Rank by simulated impact (clears red first, then highest min EOD).
  5. Apply = month-scoped planned cancel+move only (never mutates global DOM rules).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from .project import Flow, breach_autopsy, project, _parse_date

_FLEX_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "category_flexibility.json"

_DEFAULT_FLEX_CONFIG = {
    "flexible": ["Savings", "Partner Allowance"],
    "fixed": [
        "Home Mortgage",
        "Car Insurance",
        "FPL",
        "Water",
        "Gas Bill",
        "AT&T",
        "Student Loans",
    ],
    "income_timing": ["Jordan's Income"],
    "prefer_order": ["Savings", "Partner Allowance"],
}

_flex_config_cache: Optional[dict] = None


def load_flexibility_config(path: Optional[Path] = None) -> dict:
    """Load flexible / fixed / income_timing category lists."""
    global _flex_config_cache
    cfg_path = Path(path) if path else _FLEX_CONFIG_PATH
    if path is None and _flex_config_cache is not None:
        return dict(_flex_config_cache)
    cfg = {k: list(v) if isinstance(v, list) else v for k, v in _DEFAULT_FLEX_CONFIG.items()}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            raw = json.load(f)
        for k in ("flexible", "fixed", "income_timing", "prefer_order"):
            if k in raw and isinstance(raw[k], list):
                cfg[k] = list(raw[k])
    if path is None:
        _flex_config_cache = dict(cfg)
    return cfg


def clear_flexibility_cache() -> None:
    global _flex_config_cache
    _flex_config_cache = None


def category_nature(category: str, config: Optional[dict] = None) -> str:
    """Return 'flexible' | 'fixed' | 'income_timing' | 'unknown'."""
    cfg = config or load_flexibility_config()
    name = (category or "").strip()
    if name in cfg.get("income_timing", []):
        return "income_timing"
    if name in cfg.get("flexible", []):
        return "flexible"
    if name in cfg.get("fixed", []):
        return "fixed"
    low = name.lower()
    if "jordan" in low and "income" in low:
        return "income_timing"
    if any(k in low for k in ("savings", "allowance", "wifes", "wife", "amazon", "outing", "gift")):
        return "flexible"
    if any(
        k in low
        for k in (
            "rocket",
            "mortgage",
            "insurance",
            "fpl",
            "water",
            "gas bill",
            "at&t",
            "utility",
            "utitlit",
            "student loan",
            "auto loan",
            "telluride",
            "kia",
        )
    ):
        return "fixed"
    return "unknown"


def _fmt_money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _flex_sort_key(category: str, prefer_order: list[str]) -> tuple:
    try:
        return (0, prefer_order.index(category), category)
    except ValueError:
        return (1, 0, category)


def _month_stats(daily: list[dict], year: int, month: int) -> dict:
    rows = [r for r in daily if r["date"].year == int(year) and r["date"].month == int(month)]
    if not rows:
        return {"min_eod": None, "neg_days": 0, "first_breach": None}
    eods = [r["eod"] for r in rows]
    return {
        "min_eod": min(eods),
        "neg_days": sum(1 for e in eods if e < 0),
        "first_breach": next((r["date"] for r in rows if r["eod"] < 0), None),
    }


def _iso(d: date | str) -> str:
    if isinstance(d, date):
        return d.isoformat()
    return str(d)[:10]


def mitigation_source_tag(year: int, month: int, category: str, kind: str = "move") -> str:
    return f"mitigation:{int(year):04d}-{int(month):02d}:{kind}:{category}"


def planned_items_for_outflow_move(
    *,
    category: str,
    amount: float,
    from_date: date,
    to_date: date,
    year: int,
    month: int,
    source: Optional[str] = None,
) -> list[dict]:
    """Month-scoped override: cancel outflow on from_date, place same amount on to_date."""
    amt = float(amount)
    if amt > 0:
        amt = -amt
    src = source or mitigation_source_tag(year, month, category, "move")
    return [
        {
            "date": _iso(from_date),
            "amount": -amt,
            "category": category,
            "label": f"Mitigation cancel {category} {_iso(from_date)} (month override)",
            "enabled": True,
            "source": src,
        },
        {
            "date": _iso(to_date),
            "amount": amt,
            "category": category,
            "label": f"Mitigation move {category} → {_iso(to_date)} (month override)",
            "enabled": True,
            "source": src,
        },
    ]


def planned_items_for_income_pull(
    *,
    category: str,
    amount: float,
    from_date: date,
    to_date: date,
    year: int,
    month: int,
    source: Optional[str] = None,
) -> list[dict]:
    """Month-scoped: pull an income inflow earlier (cancel on from, place on to)."""
    amt = abs(float(amount))
    src = source or mitigation_source_tag(year, month, category, "income_pull")
    return [
        {
            "date": _iso(from_date),
            "amount": -amt,
            "category": category,
            "label": f"Mitigation defer {category} {_iso(from_date)} (month override)",
            "enabled": True,
            "source": src,
        },
        {
            "date": _iso(to_date),
            "amount": amt,
            "category": category,
            "label": f"Mitigation pull {category} → {_iso(to_date)} (month override)",
            "enabled": True,
            "source": src,
        },
    ]


def _apply_planned_overlay(planned: list[dict], extra: list[dict]) -> list[dict]:
    return list(planned or []) + list(extra or [])


def simulate_planned_overlay(
    *,
    start_date: date,
    end_date: date,
    start_balance: float,
    rules: list[dict],
    planned: list[dict],
    actuals: Optional[list[dict]],
    extra_planned: list[dict],
    warning_threshold: float = 100.0,
    suppress_rules_through: Optional[date] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    res = project(
        start_date,
        end_date,
        start_balance,
        rules,
        _apply_planned_overlay(planned, extra_planned),
        actuals or [],
        None,
        warning_threshold,
        suppress_rules_through=suppress_rules_through,
    )
    out: dict[str, Any] = {
        "summary": res["summary"],
        "months": res["months"],
        "daily": res["daily"],
    }
    if year is not None and month is not None:
        stats = _month_stats(res["daily"], year, month)
        out.update(
            {
                "month_min_eod": stats["min_eod"],
                "month_neg_days": stats["neg_days"],
                "month_first_breach": stats["first_breach"],
                "clears_first_breach": stats["first_breach"] is None,
            }
        )
    return out


def _next_paycheck_after(
    daily: list[dict], after: date, *, prefer_categories: Optional[tuple[str, ...]] = None
) -> Optional[dict]:
    """Find next sizable income day after ``after`` (prefer Alex paycheck)."""
    prefer = prefer_categories or ("Alex's Income", "Alex")
    by_date = {r["date"]: r for r in daily}
    ordered = sorted(d for d in by_date if d > after)
    best = None
    for d in ordered:
        row = by_date[d]
        pos = [f for f in (row.get("flows") or []) if f.amount > 0]
        if not pos:
            continue
        # Prefer primary-earner labeled inflows
        preferred = [
            f
            for f in pos
            if any(p.lower() in f"{f.category} {f.label}".lower() for p in prefer)
        ]
        pick = max(preferred or pos, key=lambda f: f.amount)
        if pick.amount < 500:
            continue
        cand = {
            "date": d,
            "amount": float(pick.amount),
            "category": pick.category,
            "label": pick.label or pick.category,
        }
        if preferred:
            return cand
        if best is None:
            best = cand
    return best


def _find_income_in_month(
    daily: list[dict], year: int, month: int, category: str
) -> list[dict]:
    out = []
    for row in daily:
        d = row["date"]
        if d.year != year or d.month != month:
            continue
        for f in row.get("flows") or []:
            if f.category == category and f.amount > 0:
                out.append(
                    {
                        "date": d,
                        "amount": float(f.amount),
                        "category": f.category,
                        "label": f.label or f.category,
                    }
                )
    return out


def _rank_key(proposal: dict) -> tuple:
    sim = proposal.get("simulation") or {}
    clears = 1 if sim.get("clears_first_breach") else 0
    min_eod = sim.get("new_min_eod")
    if min_eod is None:
        min_eod = float("-inf")
    # Prefer: clears red, then higher min EOD, then prefer_order / nature
    nature_rank = {"flexible": 0, "income_timing": 1, "fixed": 9, "unknown": 5}.get(
        proposal.get("nature"), 5
    )
    prefer = proposal.get("prefer_rank", 99)
    return (-clears, -float(min_eod), nature_rank, prefer)


def mitigation_suggestions(
    daily: list[dict],
    year: int,
    month: int,
    *,
    start_date: date,
    end_date: date,
    start_balance: float,
    rules: list[dict],
    planned: Optional[list[dict]] = None,
    actuals: Optional[list[dict]] = None,
    warning_threshold: float = 100.0,
    suppress_rules_through: Optional[date] = None,
    autopsy: Optional[dict] = None,
    flex_config: Optional[dict] = None,
) -> Optional[dict]:
    """Analyze a red month and return ranked mitigation proposals.

    Proposal kinds:
      - shift_flexible: move flexible outflow to on/after next paycheck
      - pull_income: request income_timing (e.g. Jordan) earlier to cover trough
      - fixed_note: fixed bill — no skip suggestion
    """
    auto = autopsy or breach_autopsy(daily, int(year), int(month))
    if not auto:
        return None

    cfg = flex_config or load_flexibility_config()
    prefer = list(cfg.get("prefer_order") or cfg.get("flexible") or [])
    planned = planned or []
    actuals = actuals or []
    breach_day: date = auto["first_breach"]
    baseline = _month_stats(daily, year, month)
    shortfall = abs(min(0.0, float(auto.get("breach_eod") or 0.0)))

    # Classify breach-day outflows
    classified = []
    for fd in auto.get("flows") or []:
        if fd["amount"] >= 0:
            continue
        nature = category_nature(fd["category"], cfg)
        classified.append(
            {
                "category": fd["category"],
                "amount": float(fd["amount"]),
                "label": fd.get("label") or fd["category"],
                "source": fd.get("source") or "",
                "nature": nature,
            }
        )

    payday_info = auto.get("next_inflow")
    if payday_info and payday_info.get("date"):
        payday = (
            payday_info["date"]
            if isinstance(payday_info["date"], date)
            else _parse_date(payday_info["date"])
        )
        payday_label = payday_info.get("category") or "paycheck"
    else:
        alt = _next_paycheck_after(daily, breach_day)
        payday = alt["date"] if alt else None
        payday_label = alt["category"] if alt else None

    proposals: list[dict] = []

    # --- Flexible shifts (dedupe by category, prefer_order) ---
    flex_by_cat: dict[str, float] = {}
    for c in classified:
        if c["nature"] != "flexible":
            continue
        flex_by_cat[c["category"]] = flex_by_cat.get(c["category"], 0.0) + c["amount"]

    if payday is not None:
        for cat in sorted(flex_by_cat.keys(), key=lambda c: _flex_sort_key(c, prefer)):
            amt = flex_by_cat[cat]
            extra = planned_items_for_outflow_move(
                category=cat,
                amount=amt,
                from_date=breach_day,
                to_date=payday,
                year=year,
                month=month,
            )
            sim = simulate_planned_overlay(
                start_date=start_date,
                end_date=end_date,
                start_balance=start_balance,
                rules=rules,
                planned=planned,
                actuals=actuals,
                extra_planned=extra,
                warning_threshold=warning_threshold,
                suppress_rules_through=suppress_rules_through,
                year=year,
                month=month,
            )
            try:
                pref_rank = prefer.index(cat)
            except ValueError:
                pref_rank = 50
            proposals.append(
                {
                    "kind": "shift_flexible",
                    "nature": "flexible",
                    "category": cat,
                    "amount": amt,
                    "from_date": breach_day,
                    "suggested_to_date": payday,
                    "payday_label": payday_label,
                    "prefer_rank": pref_rank,
                    "applicable": True,
                    "planned_items": extra,
                    "simulation": {
                        "clears_first_breach": sim["clears_first_breach"],
                        "new_min_eod": sim["month_min_eod"],
                        "new_neg_days": sim["month_neg_days"],
                        "new_first_breach": sim["month_first_breach"],
                    },
                    "summary": (
                        f"Move {cat} ({_fmt_money(amt)}) from {_iso(breach_day)} → "
                        f"{_iso(payday)} ({payday_label})"
                    ),
                }
            )

    # --- Income timing: pull Jordan (etc.) onto/before breach day ---
    for cat in cfg.get("income_timing") or []:
        incomes = _find_income_in_month(daily, year, month, cat)
        # Also search nearby month if pay is after breach in same month only
        if not incomes:
            continue
        for inc in incomes:
            if inc["date"] <= breach_day:
                # Already on or before breach — pulling earlier within month may still help
                # if it lands after prior trough; only suggest if after breach... skip if already early
                continue
            # Pull to breach day (or day before if we want buffer — use breach day)
            to_date = breach_day
            extra = planned_items_for_income_pull(
                category=cat,
                amount=inc["amount"],
                from_date=inc["date"],
                to_date=to_date,
                year=year,
                month=month,
            )
            sim = simulate_planned_overlay(
                start_date=start_date,
                end_date=end_date,
                start_balance=start_balance,
                rules=rules,
                planned=planned,
                actuals=actuals,
                extra_planned=extra,
                warning_threshold=warning_threshold,
                suppress_rules_through=suppress_rules_through,
                year=year,
                month=month,
            )
            covers = abs(inc["amount"]) >= shortfall - 1e-6
            proposals.append(
                {
                    "kind": "pull_income",
                    "nature": "income_timing",
                    "category": cat,
                    "amount": float(inc["amount"]),
                    "from_date": inc["date"],
                    "suggested_to_date": to_date,
                    "payday_label": None,
                    "prefer_rank": 80,
                    "applicable": True,
                    "covers_shortfall": covers,
                    "planned_items": extra,
                    "simulation": {
                        "clears_first_breach": sim["clears_first_breach"],
                        "new_min_eod": sim["month_min_eod"],
                        "new_neg_days": sim["month_neg_days"],
                        "new_first_breach": sim["month_first_breach"],
                    },
                    "summary": (
                        f"Request {cat} ({_fmt_money(float(inc['amount']))}) earlier: "
                        f"{_iso(inc['date'])} → {_iso(to_date)}"
                        + (" — covers trough" if covers else " — partial cover")
                    ),
                }
            )

    # --- Fixed notes (no apply) ---
    fixed_seen = set()
    for c in classified:
        if c["nature"] != "fixed":
            continue
        if c["category"] in fixed_seen:
            continue
        fixed_seen.add(c["category"])
        proposals.append(
            {
                "kind": "fixed_note",
                "nature": "fixed",
                "category": c["category"],
                "amount": c["amount"],
                "from_date": breach_day,
                "suggested_to_date": None,
                "prefer_rank": 90,
                "applicable": False,
                "planned_items": [],
                "simulation": {
                    "clears_first_breach": False,
                    "new_min_eod": baseline["min_eod"],
                    "new_neg_days": baseline["neg_days"],
                    "new_first_breach": baseline["first_breach"],
                },
                "summary": (
                    f"{c['category']} ({_fmt_money(c['amount'])}) is fixed — "
                    "do not skip; no timing lever unless you mark it flexible."
                ),
            }
        )

    # Cumulative flexible plan (prefer_order): keep adding until clear
    recommended: list[dict] = []
    cum_items: list[dict] = []
    still_red = baseline["first_breach"] is not None
    flex_props = sorted(
        [p for p in proposals if p["kind"] == "shift_flexible"],
        key=lambda p: _flex_sort_key(p["category"], prefer),
    )
    for p in flex_props:
        if not still_red:
            break
        trial = cum_items + list(p["planned_items"])
        sim = simulate_planned_overlay(
            start_date=start_date,
            end_date=end_date,
            start_balance=start_balance,
            rules=rules,
            planned=planned,
            actuals=actuals,
            extra_planned=trial,
            warning_threshold=warning_threshold,
            suppress_rules_through=suppress_rules_through,
            year=year,
            month=month,
        )
        cum_items = trial
        rec = dict(p)
        rec["simulation"] = {
            "clears_first_breach": sim["clears_first_breach"],
            "new_min_eod": sim["month_min_eod"],
            "new_neg_days": sim["month_neg_days"],
            "new_first_breach": sim["month_first_breach"],
            "cumulative": True,
        }
        recommended.append(rec)
        still_red = not sim["clears_first_breach"]

    # If flexible plan still red, consider best income pull as add-on
    if still_red:
        income_props = [
            p for p in proposals if p["kind"] == "pull_income" and p["simulation"]["clears_first_breach"]
        ]
        income_props.sort(key=_rank_key)
        if income_props:
            # Prefer income alone if it clears; else add to cum
            best_inc = income_props[0]
            if not recommended:
                recommended.append(best_inc)
                cum_items = list(best_inc["planned_items"])
            else:
                trial = cum_items + list(best_inc["planned_items"])
                sim = simulate_planned_overlay(
                    start_date=start_date,
                    end_date=end_date,
                    start_balance=start_balance,
                    rules=rules,
                    planned=planned,
                    actuals=actuals,
                    extra_planned=trial,
                    warning_threshold=warning_threshold,
                    suppress_rules_through=suppress_rules_through,
                    year=year,
                    month=month,
                )
                if sim["clears_first_breach"] or (
                    sim["month_min_eod"] is not None
                    and baseline["min_eod"] is not None
                    and sim["month_min_eod"] > baseline["min_eod"]
                ):
                    rec = dict(best_inc)
                    rec["simulation"] = {
                        "clears_first_breach": sim["clears_first_breach"],
                        "new_min_eod": sim["month_min_eod"],
                        "new_neg_days": sim["month_neg_days"],
                        "new_first_breach": sim["month_first_breach"],
                        "cumulative": True,
                    }
                    recommended.append(rec)
                    cum_items = trial
            still_red = _month_stats(
                simulate_planned_overlay(
                    start_date=start_date,
                    end_date=end_date,
                    start_balance=start_balance,
                    rules=rules,
                    planned=planned,
                    actuals=actuals,
                    extra_planned=cum_items,
                    warning_threshold=warning_threshold,
                    suppress_rules_through=suppress_rules_through,
                    year=year,
                    month=month,
                )["daily"],
                year,
                month,
            )["first_breach"] is not None

    plan_sim = None
    if cum_items:
        plan_sim = simulate_planned_overlay(
            start_date=start_date,
            end_date=end_date,
            start_balance=start_balance,
            rules=rules,
            planned=planned,
            actuals=actuals,
            extra_planned=cum_items,
            warning_threshold=warning_threshold,
            suppress_rules_through=suppress_rules_through,
            year=year,
            month=month,
        )

    # Rank all applicable proposals for display
    ranked = sorted(
        [p for p in proposals if p.get("applicable")],
        key=_rank_key,
    )
    # Append fixed notes at end
    ranked.extend([p for p in proposals if p["kind"] == "fixed_note"])

    note = None
    if not any(p["kind"] == "shift_flexible" for p in proposals) and not any(
        p["kind"] == "pull_income" for p in proposals
    ):
        note = "No flexible or income-timing lever on the breach day — fixed bills only."

    return {
        "year": int(year),
        "month": int(month),
        "first_breach": breach_day,
        "breach_eod": float(auto.get("breach_eod") or 0),
        "shortfall": shortfall,
        "payday": payday,
        "payday_label": payday_label,
        "baseline": baseline,
        "classified_outflows": classified,
        "proposals": ranked,
        "recommended": recommended,
        "recommended_planned_items": cum_items,
        "plan_clears_breach": bool(plan_sim and plan_sim.get("clears_first_breach")),
        "plan_min_eod": plan_sim.get("month_min_eod") if plan_sim else None,
        "plan_neg_days": plan_sim.get("month_neg_days") if plan_sim else None,
        "note": note,
    }


def apply_mitigation_to_planned(
    existing_planned: list[dict],
    mitigation: dict,
    *,
    which: str = "recommended",
    proposal_index: Optional[int] = None,
) -> list[dict]:
    """Return a new planned list with month-scoped mitigation items applied.

    Removes prior mitigation sources for the same year-month categories being applied,
    then appends the new planned offsets. Does not touch DB.
    """
    if which == "proposal" and proposal_index is not None:
        props = mitigation.get("proposals") or []
        prop = props[proposal_index]
        items = list(prop.get("planned_items") or [])
    else:
        items = list(mitigation.get("recommended_planned_items") or [])
        if not items:
            # fallback: first applicable proposal that clears
            for p in mitigation.get("proposals") or []:
                if p.get("applicable") and (p.get("simulation") or {}).get("clears_first_breach"):
                    items = list(p.get("planned_items") or [])
                    break
            if not items:
                for p in mitigation.get("recommended") or []:
                    items = list(p.get("planned_items") or [])
                    if items:
                        break

    if not items:
        return list(existing_planned or [])

    sources = {it.get("source") for it in items if it.get("source")}
    # Also clear any mitigation:* for same year-month
    y, m = mitigation["year"], mitigation["month"]
    prefix = f"mitigation:{int(y):04d}-{int(m):02d}:"
    kept = [
        p
        for p in (existing_planned or [])
        if not (str(p.get("source") or "").startswith(prefix) or p.get("source") in sources)
    ]
    return kept + items


def apply_mitigation_db(conn, mitigation: dict, *, proposal: Optional[dict] = None) -> list[int]:
    """Persist month-scoped mitigation planned items via db helpers.

    Clears existing mitigation sources for that year-month, then inserts new ones.
    Returns new planned item ids.
    """
    from . import db as dbmod

    y, m = int(mitigation["year"]), int(mitigation["month"])
    prefix = f"mitigation:{y:04d}-{m:02d}:"
    # Delete prior mitigation rows for this month
    rows = dbmod.list_planned(conn)
    for p in rows:
        src = p.get("source") or ""
        if src.startswith(prefix) and p.get("id") is not None:
            dbmod.delete_planned(conn, int(p["id"]))

    if proposal is not None:
        items = list(proposal.get("planned_items") or [])
    else:
        items = list(mitigation.get("recommended_planned_items") or [])
        if not items and mitigation.get("recommended"):
            for r in mitigation["recommended"]:
                items.extend(r.get("planned_items") or [])

    ids = []
    for it in items:
        ids.append(dbmod.add_planned(conn, it))
    return ids


def _day_ordinal(d: date | str) -> str:
    if isinstance(d, date):
        n = d.day
    else:
        n = int(str(d)[8:10])
    if 10 <= (n % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _compact_outflow_money(amount: float) -> str:
    """Format as −$3500 (whole dollars) or −$3,500.50."""
    x = abs(float(amount))
    if abs(x - round(x)) < 1e-6:
        return f"−${int(round(x)):,}"
    return f"−${x:,.2f}"


def parse_mitigation_source(source: str) -> Optional[dict]:
    """Parse ``mitigation:YYYY-MM:kind:Category`` → dict or None."""
    src = str(source or "")
    if not src.startswith("mitigation:"):
        return None
    parts = src.split(":", 3)
    if len(parts) < 4:
        return None
    ym, kind, category = parts[1], parts[2], parts[3]
    try:
        year, month = int(ym[:4]), int(ym[5:7])
    except (ValueError, IndexError):
        return None
    return {"year": year, "month": month, "kind": kind, "category": category, "source": src}


def format_mitigation_oneliner(
    year: int,
    month: int,
    *,
    category: str,
    amount: float,
    from_date: date | str,
    to_date: date | str,
    kind: str = "move",
    clears: Optional[bool] = None,
    status: Optional[str] = None,
) -> str:
    """One-line Dashboard blurb, e.g. ``2027-01: Move Savings −$3500 from 28th → 29th — clears red``.

    Only pass ``clears=True`` / status containing "cleared" when a simulation
    (or live projection) confirms the month is no longer red.
    """
    label = f"{int(year):04d}-{int(month):02d}"
    money = _compact_outflow_money(amount)

    def _as_date(d: date | str) -> date:
        return d if isinstance(d, date) else _parse_date(d)

    fd, td = _as_date(from_date), _as_date(to_date)
    # Same calendar month → "28th → 29th"; otherwise keep ISO for clarity
    if fd.year == td.year and fd.month == td.month:
        fr, to = _day_ordinal(fd), _day_ordinal(td)
    else:
        fr, to = _iso(fd), _iso(td)
    if kind in ("move", "shift_flexible"):
        body = f"Move {category} {money} from {fr} → {to}"
    elif kind in ("income_pull", "pull_income"):
        body = f"Request {category} earlier: {fr} → {to}"
    else:
        body = f"{category} {money} ({fr} → {to})"
    if status:
        return f"{label}: {body} — {status}"
    if clears is True:
        return f"{label}: {body} — clears red"
    if clears is False:
        return f"{label}: {body} — still red"
    return f"{label}: {body}"


def list_applied_mitigations(planned: Optional[list[dict]] = None) -> list[dict]:
    """Infer applied month-scoped mitigations from planned ``mitigation:…`` sources.

    Returns chronological entries with year/month/category/kind/from_date/to_date/amount/oneliner.
    """
    groups: dict[str, list[dict]] = {}
    for p in planned or []:
        src = str(p.get("source") or "")
        meta = parse_mitigation_source(src)
        if not meta:
            continue
        groups.setdefault(src, []).append(p)

    out: list[dict] = []
    for src, items in groups.items():
        meta = parse_mitigation_source(src)
        assert meta is not None
        kind = meta["kind"]
        category = meta["category"]
        year, month = meta["year"], meta["month"]

        # Normalize dates
        dated = []
        for it in items:
            d = it.get("date")
            if isinstance(d, date):
                dd = d
            else:
                dd = _parse_date(d) if d else None
            if dd is None:
                continue
            dated.append((dd, float(it.get("amount") or 0.0), it))

        if not dated:
            continue
        dated.sort(key=lambda t: t[0])

        from_date = dated[0][0]
        to_date = dated[-1][0]
        amount = 0.0
        if kind == "move":
            # cancel = positive offset; move = negative outflow on later day
            cancels = [t for t in dated if t[1] > 0]
            moves = [t for t in dated if t[1] < 0]
            if cancels:
                from_date = cancels[0][0]
                amount = -abs(cancels[0][1])
            if moves:
                to_date = moves[0][0]
                amount = moves[0][1]
        elif kind == "income_pull":
            # defer (negative on original) then pull (positive earlier)
            defers = [t for t in dated if t[1] < 0]
            pulls = [t for t in dated if t[1] > 0]
            if defers:
                from_date = defers[0][0]
            if pulls:
                to_date = pulls[0][0]
                amount = pulls[0][1]
            else:
                amount = abs(dated[0][1])
        else:
            amount = dated[0][1]

        # Never claim "red cleared" here — that requires a live simulation.
        # Callers that know the month is no longer red can pass clears=True.
        oneliner = format_mitigation_oneliner(
            year,
            month,
            category=category,
            amount=amount if amount < 0 else -abs(amount) if kind == "move" else amount,
            from_date=from_date,
            to_date=to_date,
            kind=kind,
            status="applied",
        )
        out.append(
            {
                "year": year,
                "month": month,
                "label": f"{year:04d}-{month:02d}",
                "kind": kind,
                "category": category,
                "from_date": from_date,
                "to_date": to_date,
                "amount": amount,
                "source": src,
                "items": items,
                "oneliner": oneliner,
                "status": "applied",
            }
        )

    out.sort(key=lambda e: (e["year"], e["month"], e["category"]))
    return out
