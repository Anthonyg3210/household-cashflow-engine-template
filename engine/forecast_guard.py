"""Forecast coverage check — flag must-have essentials missing from the forward view.

Prevents repeats of dropped forecast items (e.g. Demo Cleaners $180 cleaning). Two passes:

  1. Catalog — each enabled essential in data/forecast_essentials.json must appear
     in the next N days of projection daily flows, or in an enabled recurring_rule
     that covers that window.
  2. History — bank_csv categories that hit ≥4 of the last 6 complete months,
     look bill-like (stable amount), and have no matching forecast line.

Does not mutate rules, planned items, start_balance, or checklist math.
"""
from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from . import db
from .project import expand_rules

_ROOT = Path(__file__).resolve().parent.parent
_CATALOG_PATH = _ROOT / "data" / "forecast_essentials.json"

DEFAULT_LOOK_AHEAD_DAYS = 90
HISTORY_MONTHS = 6
HISTORY_MIN_MONTHS = 4
HISTORY_MIN_TYPICAL = 25.0

# Variable / card / grocery spend — not "must-have forecast lines"
_HISTORY_SKIP_EXACT = {
    "groceries",
    "dining",
    "shopping",
    "amazon",
    "fast food / food outings",
    "family outings",
    "other outings",
    "malls",
    "gift",
    "afterpay",
    "holiday gifts / purchases",
    "other (if applicable, provide a description)",
    "apple card",
    "citi card",
    "synchrony",
    "meriott chase",
    "marriott chase",
}
_HISTORY_SKIP_SUBSTR = (
    "grocery",
    "publix",
    "whole foods",
    "costco",
    "walmart",
    "target",
    "amazon",
    "doordash",
    "ubereats",
    "uber eats",
    "restaurant",
    "dining",
    "atm withdrawal",
    "payment thank you",
    "debit card purchase",
)

_catalog_cache: Optional[dict] = None


def _parse_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_label(ym: str) -> str:
    try:
        y, m = int(ym[:4]), int(ym[5:7])
        names = (
            "",
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
        return f"{names[m]} {y}"
    except (TypeError, ValueError, IndexError):
        return ym


def _month_range_label(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return _month_label(_month_key(start))
    a = _month_label(_month_key(start))
    b = _month_label(_month_key(end))
    return f"{a}–{b}"


def _flow_get(f: Any, key: str, default=None):
    if isinstance(f, dict):
        return f.get(key, default)
    return getattr(f, key, default)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("&", "and").split())


def _money(n: float) -> str:
    return f"${abs(float(n)):,.0f}"


def load_essentials_catalog(path: Optional[Path] = None) -> dict:
    """Load the editable essentials catalog (cached for the default path)."""
    global _catalog_cache
    cfg_path = Path(path) if path else _CATALOG_PATH
    if path is None and _catalog_cache is not None:
        return dict(_catalog_cache)
    raw: dict = {"look_ahead_days": DEFAULT_LOOK_AHEAD_DAYS, "essentials": []}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            raw = loaded
        elif isinstance(loaded, list):
            raw = {"essentials": loaded}
    if path is None:
        _catalog_cache = dict(raw)
    return dict(raw)


def clear_catalog_cache() -> None:
    global _catalog_cache
    _catalog_cache = None


def enabled_essentials(catalog: Optional[dict] = None) -> list[dict]:
    cat = catalog if catalog is not None else load_essentials_catalog()
    items = cat.get("essentials") if isinstance(cat, dict) else cat
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if it.get("enabled", True) is False:
            continue
        if not (it.get("id") and it.get("name")):
            continue
        out.append(it)
    return out


def _text_match(essential: dict, category: str | None, label: str | None) -> bool:
    hay_raw = f"{category or ''} {label or ''}"
    hay_l = hay_raw.lower()
    hay_n = _norm(hay_raw)
    for m in essential.get("match") or []:
        if not m:
            continue
        token = str(m)
        if token.lower() in hay_l:
            return True
        if _norm(token) and _norm(token) in hay_n:
            return True
    return False


def _amount_in_band(essential: dict, amount: float) -> bool:
    mag = abs(float(amount or 0))
    lo = essential.get("amount_min")
    hi = essential.get("amount_max")
    if lo is None and hi is None:
        return mag > 0
    if lo is not None and mag < float(lo) - 1e-6:
        return False
    if hi is not None and mag > float(hi) + 1e-6:
        return False
    return True


def _window(as_of: date, look_ahead_days: int) -> tuple[date, date]:
    start = as_of
    end = as_of + timedelta(days=int(look_ahead_days))
    return start, end


def _iter_months(start: date, end: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def _off_months(essential: dict) -> set[int]:
    raw = essential.get("off_months") or []
    return {int(x) for x in raw}


def _in_season_months(start: date, end: date, essential: dict) -> list[tuple[int, int]]:
    off = _off_months(essential)
    return [(y, m) for y, m in _iter_months(start, end) if m not in off]


def _expected_count(essential: dict, start: date, end: date, look_ahead_days: int) -> int:
    cadence = (essential.get("cadence") or "monthly").lower()
    months = _in_season_months(start, end, essential)
    if cadence.startswith("biweek"):
        return max(3, int(look_ahead_days) // 21)
    # Partial last month (e.g. window ends Dec 12) often misses a mid-month DOM.
    return max(0, max(1, len(months) - 1) if months else 0)


def _expected_amount_label(essential: dict) -> str:
    lo = essential.get("amount_min")
    hi = essential.get("amount_max")
    if lo is None and hi is None:
        return "the usual amount"
    if lo is not None and hi is not None and abs(float(hi) - float(lo)) < 1:
        return _money(float(lo))
    if lo is not None and hi is not None:
        mid = (float(lo) + float(hi)) / 2.0
        # Prefer a round "about" when the band is a tolerance around a known bill
        if float(lo) >= 140 and float(hi) <= 220:
            return "about $180"
        if 2600 <= float(lo) and float(hi) <= 3100:
            return "about $2,871"
        if 950 <= float(lo) and float(hi) <= 1200:
            return "about $1,081"
        if 3000 <= float(lo) and float(hi) <= 4000:
            return "about $3,500"
        if 1400 <= float(lo) and float(hi) <= 2200:
            return "about $1,500"
        if 4000 <= float(lo) and float(hi) <= 5200:
            return "about $4,505"
        if 450 <= float(lo) and float(hi) <= 800:
            return "about $600"
        return f"about {_money(mid)}"
    if lo is not None:
        return f"at least {_money(float(lo))}"
    return f"up to {_money(float(hi))}"


def _collect_daily_flows(daily: Iterable[dict] | None, start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    for day in daily or []:
        if isinstance(day, dict):
            d = _parse_date(day.get("date"))
            flows = day.get("flows") or []
        else:
            d = _parse_date(getattr(day, "date", None))
            flows = getattr(day, "flows", None) or []
        if d is None or d < start or d > end:
            continue
        for f in flows:
            amt = float(_flow_get(f, "amount") or 0)
            rows.append(
                {
                    "date": d,
                    "amount": amt,
                    "category": str(_flow_get(f, "category") or ""),
                    "label": str(_flow_get(f, "label") or ""),
                    "source": str(_flow_get(f, "source") or ""),
                }
            )
    return rows


def _match_flows(flows: list[dict], essential: dict) -> tuple[list[dict], list[dict]]:
    in_band: list[dict] = []
    text_only: list[dict] = []
    for f in flows:
        if not _text_match(essential, f.get("category"), f.get("label")):
            continue
        if _amount_in_band(essential, float(f.get("amount") or 0)):
            in_band.append(f)
        else:
            text_only.append(f)
    return in_band, text_only


def _rule_flows_for_essential(
    rules: list[dict],
    essential: dict,
    start: date,
    end: date,
    suppress_rules_through: date | None,
    actuals: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    matched = [
        r
        for r in rules
        if r.get("enabled", True)
        and _text_match(essential, r.get("category"), r.get("label"))
    ]
    if not matched:
        return [], []
    expanded = expand_rules(
        matched,
        start,
        end,
        suppress_rules_through=suppress_rules_through,
        actuals=actuals,
    )
    as_dicts = [
        {
            "date": f.date,
            "amount": float(f.amount),
            "category": f.category,
            "label": f.label or "",
            "source": "rule",
        }
        for f in expanded
    ]
    return _match_flows(as_dicts, essential)


def _catalog_finding(
    essential: dict,
    *,
    as_of: date,
    start: date,
    end: date,
    look_ahead_days: int,
    daily_in_band: list[dict],
    daily_text: list[dict],
    rule_in_band: list[dict],
    rule_text: list[dict],
) -> dict:
    name = essential.get("name") or essential.get("id") or "Essential"
    amt_s = _expected_amount_label(essential)
    cadence = (essential.get("cadence") or "monthly").lower()
    cadence_s = "every other week" if cadence.startswith("biweek") else "each month"
    window_s = _month_range_label(start, end)
    notes = (essential.get("notes") or "").strip()
    expected = _expected_count(essential, start, end, look_ahead_days)
    off = sorted(_off_months(essential))
    off_note = ""
    if off:
        mon = {6: "Jun", 7: "Jul"}.get
        off_s = "–".join(mon(m, str(m)) for m in off)
        off_note = f" (summer off {off_s})" if off == [6, 7] else f" (off months {off})"

    n_daily = len(daily_in_band)
    n_rule = len(rule_in_band)
    has_in_band = n_daily > 0 or n_rule > 0
    has_text = len(daily_text) > 0 or len(rule_text) > 0

    if expected == 0 and _off_months(essential):
        severity = "ok"
        title = f"{name} is not expected this window"
        detail = (
            f"{name} is in-season off{off_note}. "
            f"No coverage needed for {window_s}."
        )
        prompt = (
            f"{name} is cataloged as off{off_note}. "
            f"Window checked: {window_s}. No action unless the season changed."
        )
    elif has_in_band:
        # Monthly: two in-band hits in 90 days (or a covering rule) is enough.
        # A single leftover stamp with no rule is "thin" — the demo-style miss is 0 hits.
        if cadence.startswith("biweek"):
            solid = n_daily >= 3 or n_rule >= 3 or (n_daily >= 1 and n_rule >= 2)
        else:
            solid = n_daily >= 2 or n_rule >= 2 or (n_daily >= 1 and n_rule >= 1)
        severity = "ok" if solid else "weak"
        src_bits = []
        if n_daily:
            src_bits.append(f"{n_daily} forecast line(s)")
        if n_rule:
            src_bits.append(f"enabled rule covering {n_rule} date(s)")
        src = " and ".join(src_bits) or "coverage"
        if severity == "ok":
            title = f"{name} is on the forecast"
            detail = (
                f"{src} in the next {look_ahead_days} days ({window_s}), "
                f"{amt_s} {cadence_s}{off_note}."
            )
            prompt = (
                f"{name} looks covered for {window_s} ({src}, {amt_s} {cadence_s}). "
                "No investigation needed unless the amount or date looks wrong to you."
            )
        else:
            title = f"{name} looks thin"
            detail = (
                f"Only {n_daily} matching forecast line(s) in the next {look_ahead_days} days "
                f"({window_s}). We expect {amt_s} {cadence_s}{off_note}."
            )
            prompt = _investigate_prompt(
                name,
                amt_s,
                cadence_s,
                window_s,
                notes,
                found=(
                    f"Only {n_daily} matching line(s) in the next {look_ahead_days} days; "
                    "no enabled rule filling the rest of the window."
                ),
                kind="thin",
            )
    elif has_text:
        sample = (daily_text or rule_text)[0]
        found_amt = _money(sample.get("amount") or 0)
        severity = "weak"
        title = f"{name} is on the books at the wrong amount"
        detail = (
            f"Found a {sample.get('category') or 'matching'} line at {found_amt}, "
            f"but we expect {amt_s} {cadence_s}{off_note}."
        )
        prompt = _investigate_prompt(
            name,
            amt_s,
            cadence_s,
            window_s,
            notes,
            found=f"A matching name is present but the amount is {found_amt}, not {amt_s}.",
            kind="wrong_amount",
        )
    else:
        severity = "missing"
        title = f"{name} is missing"
        detail = (
            f"We expect {amt_s} {cadence_s}{off_note}. "
            f"Nothing matching is in the next {look_ahead_days} days ({window_s}), "
            "and no enabled recurring rule covers that window."
        )
        prompt = _investigate_prompt(
            name,
            amt_s,
            cadence_s,
            window_s,
            notes,
            found=(
                f"No matching forecast line and no enabled recurring rule in {window_s}."
            ),
            kind="missing",
        )

    return {
        "id": str(essential.get("id") or name),
        "source": "catalog",
        "severity": severity,
        "title": title,
        "detail": detail,
        "investigate_prompt": prompt,
        "name": name,
        "expected_count": expected,
        "daily_hits": n_daily,
        "rule_hits": n_rule,
    }


def _investigate_prompt(
    name: str,
    amt_s: str,
    cadence_s: str,
    window_s: str,
    notes: str,
    *,
    found: str,
    kind: str,
) -> str:
    why = {
        "missing": "it is not on the forward forecast",
        "thin": "coverage looks thinner than a full cadence",
        "wrong_amount": "the name is present but the dollar amount is off",
        "history": "Chase history looks recurring but the forecast does not have it",
    }.get(kind, "it needs a look")
    lines = [
        f"Please investigate: {name} ({amt_s}, {cadence_s}) — {why}.",
        f"Window: {window_s}.",
        f"What we found: {found}",
    ]
    if notes:
        lines.append(f"Catalog note: {notes}")
    lines.append(
        "Ask: was this already paid, paused, or dropped from Budget workbook / Data Input? "
        "If it still happens, add or restore the recurring rule so we do not miss it again."
    )
    return "\n".join(lines)


def _last_complete_months(as_of: date, n: int = HISTORY_MONTHS) -> list[str]:
    y, m = as_of.year, as_of.month
    if m == 1:
        y, m = y - 1, 12
    else:
        m -= 1
    out: list[str] = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
    return list(reversed(out))


def _history_skip_category(category: str, label: str = "") -> bool:
    cat = (category or "").strip()
    low = cat.lower()
    if low in _HISTORY_SKIP_EXACT:
        return True
    blob = f"{cat} {label or ''}".lower()
    return any(s in blob for s in _HISTORY_SKIP_SUBSTR)


def _stable_amounts(amounts: list[float]) -> bool:
    if len(amounts) < 2:
        return True
    lo, hi = min(amounts), max(amounts)
    if lo <= 0:
        return False
    if hi > lo * 2.5:
        return False
    if len(amounts) >= 3:
        try:
            med = statistics.median(amounts)
            if med <= 0:
                return False
            spread = statistics.pstdev(amounts) / med
            if spread > 0.55:
                return False
        except statistics.StatisticsError:
            return True
    return True


def _forecast_matches_history(
    forecast_flows: list[dict], category: str, typical: float
) -> bool:
    cat_n = _norm(category)
    if not cat_n:
        return False
    for f in forecast_flows:
        hay = _norm(f"{f.get('category') or ''} {f.get('label') or ''}")
        if cat_n not in hay and _norm(f.get("category") or "") != cat_n:
            continue
        mag = abs(float(f.get("amount") or 0))
        if typical <= 0 or abs(mag - typical) / max(typical, 1.0) <= 0.45 or mag >= 20:
            # Same category in the forecast is enough; amount band is a soft check
            if cat_n in hay:
                return True
    return False


def _history_findings(
    actuals: list[dict],
    forecast_flows: list[dict],
    catalog_items: list[dict],
    as_of: date,
    start: date,
    end: date,
    look_ahead_days: int,
) -> list[dict]:
    months = _last_complete_months(as_of, HISTORY_MONTHS)
    month_set = set(months)
    by_cat: dict[str, list[dict]] = {}
    for a in actuals or []:
        if (a.get("source") or "") != "bank_csv":
            continue
        if a.get("enabled", True) is False:
            continue
        d = _parse_date(a.get("date"))
        if d is None:
            continue
        mk = _month_key(d)
        if mk not in month_set:
            continue
        cat = (a.get("category") or "").strip()
        if not cat:
            continue
        if _history_skip_category(cat, str(a.get("label") or "")):
            continue
        # Don't double-flag catalog essentials
        if any(_text_match(ess, cat, a.get("label")) for ess in catalog_items):
            continue
        by_cat.setdefault(cat, []).append(
            {
                "date": d,
                "month": mk,
                "amount": float(a.get("amount") or 0),
                "label": a.get("label") or "",
            }
        )

    window_s = _month_range_label(start, end)
    hist_range = f"{_month_label(months[0])}–{_month_label(months[-1])}" if months else ""
    findings: list[dict] = []
    for cat, rows in sorted(by_cat.items()):
        hit_months = sorted({r["month"] for r in rows})
        if len(hit_months) < HISTORY_MIN_MONTHS:
            continue
        mags = [abs(r["amount"]) for r in rows if abs(r["amount"]) > 0]
        if not mags:
            continue
        typical = float(statistics.median(mags))
        if typical < HISTORY_MIN_TYPICAL:
            continue
        if not _stable_amounts(mags):
            continue
        if _forecast_matches_history(forecast_flows, cat, typical):
            continue
        n = len(hit_months)
        title = f"{cat} looks recurring in Chase, but isn’t forecasted"
        detail = (
            f"Chase has {cat} in {n} of the last {HISTORY_MONTHS} complete months "
            f"({hist_range}), typically {_money(typical)}. "
            f"No matching line in the next {look_ahead_days} days ({window_s})."
        )
        prompt = _investigate_prompt(
            cat,
            f"about {_money(typical)}",
            "each month",
            window_s,
            f"Seen in {', '.join(_month_label(m) for m in hit_months)} on Chase.",
            found=(
                f"Recurring in {n}/{HISTORY_MONTHS} recent complete months, "
                f"but absent from the {window_s} forecast."
            ),
            kind="history",
        )
        findings.append(
            {
                "id": f"history:{_norm(cat).replace(' ', '_')}",
                "source": "history",
                "severity": "missing",
                "title": title,
                "detail": detail,
                "investigate_prompt": prompt,
                "name": cat,
                "history_months": hit_months,
                "typical_amount": typical,
            }
        )
    return findings


def run_coverage_check(
    conn,
    daily,
    as_of,
    look_ahead_days: int = DEFAULT_LOOK_AHEAD_DAYS,
    *,
    catalog: Optional[dict] = None,
    actuals: Optional[list[dict]] = None,
    rules: Optional[list[dict]] = None,
    suppress_rules_through: Optional[date] = None,
) -> list[dict]:
    """Return coverage findings (severity missing | weak | ok).

    ``daily`` is the projection daily list (same shape as ``project()['daily']``).
    Catalog pass uses those flows plus enabled ``recurring_rules``. History pass
    reads bank_csv actuals (from ``conn`` unless ``actuals`` is passed).
    """
    as_of_d = _parse_date(as_of) or date.today()
    cat = catalog if catalog is not None else load_essentials_catalog()
    if look_ahead_days is None:
        look_ahead_days = int(cat.get("look_ahead_days") or DEFAULT_LOOK_AHEAD_DAYS)
    look_ahead_days = int(look_ahead_days or DEFAULT_LOOK_AHEAD_DAYS)
    start, end = _window(as_of_d, look_ahead_days)

    rule_list = list(rules) if rules is not None else []
    actual_list = list(actuals) if actuals is not None else []
    suppress = suppress_rules_through
    if conn is not None:
        if rules is None:
            rule_list = db.list_rules(conn)
        if actuals is None:
            actual_list = db.list_actuals(conn)
        if suppress is None:
            try:
                suppress = db.get_settings(conn).get("suppress_rules_through")
            except Exception:
                suppress = None

    essentials = enabled_essentials(cat)
    daily_flows = _collect_daily_flows(daily, start, end)

    findings: list[dict] = []
    for ess in essentials:
        d_in, d_text = _match_flows(daily_flows, ess)
        r_in, r_text = _rule_flows_for_essential(
            rule_list, ess, start, end, suppress, actuals=actual_list
        )
        findings.append(
            _catalog_finding(
                ess,
                as_of=as_of_d,
                start=start,
                end=end,
                look_ahead_days=look_ahead_days,
                daily_in_band=d_in,
                daily_text=d_text,
                rule_in_band=r_in,
                rule_text=r_text,
            )
        )

    findings.extend(
        _history_findings(
            actual_list,
            daily_flows,
            essentials,
            as_of_d,
            start,
            end,
            look_ahead_days,
        )
    )
    return findings


def summarize_coverage(findings: list[dict]) -> dict:
    """Split findings and pick a panel level: green | amber | red."""
    missing = [f for f in findings if f.get("severity") == "missing"]
    weak = [f for f in findings if f.get("severity") == "weak"]
    ok = [f for f in findings if f.get("severity") == "ok"]
    if missing:
        level = "red"
    elif weak:
        level = "amber"
    else:
        level = "green"
    return {
        "level": level,
        "missing": missing,
        "weak": weak,
        "ok": ok,
        "gaps": missing + weak,
    }


def gap_prompts(findings: list[dict]) -> str:
    """Join investigate prompts for gaps (copy-friendly)."""
    bits = []
    for f in findings:
        if f.get("severity") not in ("missing", "weak"):
            continue
        p = (f.get("investigate_prompt") or "").strip()
        if p:
            bits.append(p)
    return "\n\n".join(bits)
