"""Daily EOD cash-flow projection engine.

Semantics (match Excel twin):
  Expenses negative, income positive.
  EOD[d] = EOD[d-1] + sum(flows[d])
  Month-end = last EOD of month.
  Negative days: EOD < 0; warning days: EOD < warning_threshold.
  Recurring day-of-month rules replay every month in range.
  Year-varying paycheck amounts via amount_by_year.
  One-off planned items on a date.
  Actuals override rule flows on the same date+category when present.
  Scenario deltas layer on top of baseline without mutating rules.
  suppress_rules_through: if set, recurring rules do not fire on dates
    <= that day (planned/actuals still apply). Used so a hand-managed
    current month from Budget workbook is not double-counted with Data Input rules.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Any, Iterable, Optional
import copy
import json


@dataclass
class Flow:
    date: date
    amount: float
    category: str
    label: str = ""
    source: str = "rule"  # rule | planned | actual | scenario


@dataclass
class ScenarioDelta:
    """A single lever change inside a named scenario."""

    kind: str  # income_change | expense_change | one_off | redirect | rule_override | disable_rule
    # Common
    label: str = ""
    # income_change / expense_change: multiply or add to matching category flows
    category: str = ""
    # mode: "add" (absolute $ per occurrence or one-shot) | "pct" | "set"
    mode: str = "add"
    amount: float = 0.0
    # Timing for one_off / redirect
    on_date: Optional[date] = None
    end_date: Optional[date] = None  # optional window for change
    start_date: Optional[date] = None
    # redirect: take a positive windfall category/date and move $ to debt payoff
    redirect_from_category: str = ""
    redirect_to_category: str = "Debt Payoff"
    redirect_amount: Optional[float] = None  # None = full matching amount
    # rule_override / disable_rule
    rule_id: Optional[int] = None
    day_of_month: Optional[int] = None
    # For income_change applied as extra recurring paycheck-style
    day_of_month_new: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("on_date", "end_date", "start_date"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioDelta":
        dd = dict(d)
        for k in ("on_date", "end_date", "start_date"):
            if dd.get(k):
                dd[k] = date.fromisoformat(dd[k]) if isinstance(dd[k], str) else dd[k]
        return cls(**{k: v for k, v in dd.items() if k in cls.__dataclass_fields__})


def _parse_date(v: Any) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _year_amount(rule: dict, year: int) -> float:
    """Resolve amount, preferring amount_by_year[year]."""
    by_year = rule.get("amount_by_year") or {}
    if isinstance(by_year, str):
        by_year = json.loads(by_year) if by_year else {}
    # keys may be str
    if year in by_year:
        return float(by_year[year])
    if str(year) in by_year:
        return float(by_year[str(year)])
    # fallback: nearest prior year, else amount
    years = sorted(int(y) for y in by_year.keys())
    prior = [y for y in years if y <= year]
    if prior:
        y = prior[-1]
        return float(by_year.get(y, by_year.get(str(y))))
    return float(rule.get("amount") or 0.0)


def _iter_days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _dom_in_month(year: int, month: int, day_of_month: int) -> Optional[date]:
    last = monthrange(year, month)[1]
    if day_of_month < 1:
        return None
    return date(year, month, min(day_of_month, last))


def _biweekly_dates(anchor: date, start: date, end: date, interval: int = 14):
    """Yield biweekly dates on/after start within [start, end], aligned to anchor."""
    if interval <= 0:
        return
    # walk back to on or before start
    d = anchor
    if d < start:
        delta = (start - d).days
        steps = delta // interval
        d = d + timedelta(days=steps * interval)
        while d < start:
            d += timedelta(days=interval)
    else:
        while d > start:
            d -= timedelta(days=interval)
        if d < start:
            d += timedelta(days=interval)
    while d <= end:
        yield d
        d += timedelta(days=interval)


def expand_rules(
    rules: Iterable[dict],
    start: date,
    end: date,
    disabled_rule_ids: Optional[set] = None,
    amount_overrides: Optional[dict] = None,
    suppress_rules_through: Optional[date] = None,
    actuals: Optional[Iterable[dict]] = None,
    apply_variable: bool = True,
    variable_plans: Optional[dict] = None,
) -> list[Flow]:
    """Expand recurring rules into dated flows.

    If suppress_rules_through is set, skip any rule occurrence on a date
    on or before that day (inclusive). Planned/actuals are unaffected.

    When apply_variable is True (default), FPL (and any override categories)
    REPLACE rule amounts from Chase-based variable_amounts for dates
    >= 2026-10-01 — never added on top of Excel stamps.
    """
    disabled_rule_ids = disabled_rule_ids or set()
    amount_overrides = amount_overrides or {}
    flows: list[Flow] = []
    _var_plans = variable_plans
    if apply_variable and _var_plans is None and actuals is not None:
        from .variable_amounts import build_plans, VARIABLE_OVERRIDE_CATEGORIES

        _var_plans = build_plans(actuals, VARIABLE_OVERRIDE_CATEGORIES)

    def _resolve_amount(rule: dict, d: date, rid) -> float:
        amt = amount_overrides.get((rid, d.year), _year_amount(rule, d.year))
        if not apply_variable:
            return float(amt)
        from .variable_amounts import apply_variable_override

        return apply_variable_override(
            rule.get("category") or "",
            d,
            float(amt),
            plans=_var_plans,
            actuals=None if _var_plans is not None else actuals,
        )
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rid = rule.get("id")
        if rid is not None and rid in disabled_rule_ids:
            continue
        cadence = (rule.get("cadence") or "monthly_dom").lower()
        category = rule.get("category") or "Uncategorized"
        label = rule.get("label") or category
        r_start = _parse_date(rule["start_date"]) if rule.get("start_date") else start
        r_end = _parse_date(rule["end_date"]) if rule.get("end_date") else end
        window_start = max(start, r_start)
        window_end = min(end, r_end)
        if window_start > window_end:
            continue

        if cadence == "biweekly":
            anchor = _parse_date(rule.get("anchor_date") or "2026-09-11")
            for d in _biweekly_dates(anchor, window_start, window_end, int(rule.get("interval_days") or 14)):
                if suppress_rules_through is not None and d <= suppress_rules_through:
                    continue
                amt = _resolve_amount(rule, d, rid)
                if amt == 0:
                    continue
                flows.append(Flow(d, float(amt), category, label, "rule"))
        elif cadence in ("annual", "yearly"):
            # Once per year on anniversary of anchor (or start_date / day_of_month).
            anchor = _parse_date(rule.get("anchor_date") or rule.get("start_date") or window_start.isoformat())
            dom = int(rule.get("day_of_month") or anchor.day)
            for y in range(window_start.year, window_end.year + 1):
                d = _dom_in_month(y, anchor.month, dom)
                if not d or d < window_start or d > window_end:
                    continue
                if suppress_rules_through is not None and d <= suppress_rules_through:
                    continue
                # Skip the anchor year if already captured as a pending/actual
                amt = _resolve_amount(rule, d, rid)
                if amt == 0:
                    continue
                flows.append(Flow(d, float(amt), category, label, "rule"))
        else:
            # monthly day-of-month
            dom = int(rule.get("day_of_month") or 1)
            y, m = window_start.year, window_start.month
            while True:
                d = _dom_in_month(y, m, dom)
                if d and window_start <= d <= window_end:
                    if suppress_rules_through is not None and d <= suppress_rules_through:
                        pass
                    else:
                        amt = _resolve_amount(rule, d, rid)
                        if amt != 0:
                            flows.append(Flow(d, float(amt), category, label, "rule"))
                # next month
                if m == 12:
                    y, m = y + 1, 1
                else:
                    m += 1
                if date(y, m, 1) > window_end:
                    break
    return flows


def expand_items(items: Iterable[dict], source: str = "planned") -> list[Flow]:
    flows = []
    for it in items:
        if it.get("enabled", True) is False:
            continue
        d = _parse_date(it["date"])
        flows.append(
            Flow(
                d,
                float(it["amount"]),
                it.get("category") or "Planned",
                it.get("label") or it.get("category") or "Planned",
                source,
            )
        )
    return flows


def apply_actuals_override(rule_flows: list[Flow], actuals: list[Flow]) -> list[Flow]:
    """Actuals override rules on the same date+category; other rule flows kept."""
    if not actuals:
        return rule_flows
    override_keys = {(a.date, a.category) for a in actuals}
    kept = [f for f in rule_flows if (f.date, f.category) not in override_keys]
    return kept + actuals


def apply_scenario_deltas(
    base_flows: list[Flow],
    deltas: list[ScenarioDelta],
    start: date,
    end: date,
    rules: list[dict],
    suppress_rules_through: Optional[date] = None,
    actuals: Optional[Iterable[dict]] = None,
) -> list[Flow]:
    """Layer scenario deltas onto baseline flows. Returns new flow list."""
    flows = list(base_flows)
    disabled: set = set()
    amount_overrides: dict = {}
    extra: list[Flow] = []

    # First pass: collect disable / rule_override that need re-expansion
    need_reexpand = False
    for delta in deltas:
        if delta.kind == "disable_rule" and delta.rule_id is not None:
            disabled.add(delta.rule_id)
            need_reexpand = True
        elif delta.kind == "rule_override" and delta.rule_id is not None:
            # override amount for all years in window, or specific
            for y in range(start.year, end.year + 1):
                amount_overrides[(delta.rule_id, y)] = delta.amount
            need_reexpand = True

    if need_reexpand:
        # Rebuild rule flows with disables/overrides; keep non-rule flows
        non_rule = [f for f in flows if f.source != "rule"]
        new_rules = expand_rules(
            rules,
            start,
            end,
            disabled,
            amount_overrides,
            suppress_rules_through=suppress_rules_through,
            actuals=actuals,
        )
        flows = new_rules + non_rule

    for delta in deltas:
        if delta.kind in ("disable_rule", "rule_override"):
            continue

        if delta.kind == "one_off":
            if not delta.on_date:
                continue
            if start <= delta.on_date <= end:
                # Merge immediately so a later redirect in the same scenario can see it
                flows.append(
                    Flow(
                        delta.on_date,
                        float(delta.amount),
                        delta.category or "Scenario",
                        delta.label or "One-off",
                        "scenario",
                    )
                )
            continue

        if delta.kind == "redirect":
            # Find positive flows matching from_category (and optional date),
            # reduce them and add debt payoff of redirect_amount (or full).
            from_cat = delta.redirect_from_category or delta.category
            target = []
            for i, f in enumerate(flows):
                if from_cat and f.category != from_cat:
                    continue
                if delta.on_date and f.date != delta.on_date:
                    continue
                if delta.start_date and f.date < delta.start_date:
                    continue
                if delta.end_date and f.date > delta.end_date:
                    continue
                if f.amount <= 0:
                    continue
                target.append(i)
            # Keep the inflow on the books, then add an equal cash outflow to debt.
            # (Zeroing the inflow AND adding debt would double-count.)
            remaining = delta.redirect_amount  # None = all matching
            for i in target:
                f = flows[i]
                take = f.amount if remaining is None else min(f.amount, remaining)
                if take <= 0:
                    continue
                flows[i] = Flow(
                    f.date, f.amount, f.category, f.label + " (earmarked)", f.source
                )
                flows.append(
                    Flow(
                        f.date,
                        -abs(take),
                        delta.redirect_to_category or "Debt Payoff",
                        delta.label or f"Redirect to {delta.redirect_to_category}",
                        "scenario",
                    )
                )
                if remaining is not None:
                    remaining -= take
                    if remaining <= 0:
                        break
            continue

        if delta.kind in ("income_change", "expense_change"):
            # Adjust matching category flows in window
            cat = delta.category
            for i, f in enumerate(flows):
                if cat and f.category != cat:
                    continue
                if delta.start_date and f.date < delta.start_date:
                    continue
                if delta.end_date and f.date > delta.end_date:
                    continue
                # For expense_change, typically targeting negative flows;
                # for income_change, positive. Apply to all matching if cat set.
                if delta.mode == "pct":
                    new_amt = f.amount * (1.0 + delta.amount / 100.0)
                elif delta.mode == "set":
                    new_amt = delta.amount
                else:  # add — add absolute to each matching occurrence
                    new_amt = f.amount + delta.amount
                flows[i] = Flow(f.date, new_amt, f.category, f.label, f.source)

            # Optional: inject new recurring income/expense on a DOM if no matches
            if delta.day_of_month_new and delta.mode == "add" and delta.amount != 0:
                y, m = start.year, start.month
                while True:
                    d = _dom_in_month(y, m, delta.day_of_month_new)
                    if d and start <= d <= end:
                        if not delta.start_date or d >= delta.start_date:
                            if not delta.end_date or d <= delta.end_date:
                                extra.append(
                                    Flow(
                                        d,
                                        float(delta.amount),
                                        delta.category or ("Income" if delta.kind == "income_change" else "Expense"),
                                        delta.label or delta.kind,
                                        "scenario",
                                    )
                                )
                    if m == 12:
                        y, m = y + 1, 1
                    else:
                        m += 1
                    if date(y, m, 1) > end:
                        break
            continue

    return flows + extra


def project(
    start_date: date,
    end_date: date,
    start_balance: float,
    rules: list[dict],
    planned: Optional[list[dict]] = None,
    actuals: Optional[list[dict]] = None,
    scenario_deltas: Optional[list[ScenarioDelta]] = None,
    warning_threshold: float = 100.0,
    suppress_rules_through: Optional[date] = None,
) -> dict:
    """Run full projection. Returns daily series + monthly aggregates + summary."""
    planned = planned or []
    actuals = actuals or []
    scenario_deltas = scenario_deltas or []

    rule_flows = expand_rules(
        rules,
        start_date,
        end_date,
        suppress_rules_through=suppress_rules_through,
        actuals=actuals,
    )
    planned_flows = expand_items(planned, "planned")
    actual_flows = expand_items(actuals, "actual")

    # Merge rule+planned, then actuals override by date+category
    merged = apply_actuals_override(rule_flows + planned_flows, actual_flows)

    if scenario_deltas:
        merged = apply_scenario_deltas(
            merged,
            scenario_deltas,
            start_date,
            end_date,
            rules,
            suppress_rules_through=suppress_rules_through,
            actuals=actuals,
        )

    # Index flows by date
    by_day: dict[date, list[Flow]] = {}
    for f in merged:
        if start_date <= f.date <= end_date:
            by_day.setdefault(f.date, []).append(f)

    daily = []
    eod = float(start_balance)
    first_breach: Optional[date] = None
    first_warning: Optional[date] = None
    min_eod = eod
    min_eod_date = start_date - timedelta(days=1)

    for d in _iter_days(start_date, end_date):
        day_flows = by_day.get(d, [])
        day_sum = sum(f.amount for f in day_flows)
        eod = eod + day_sum
        if eod < min_eod:
            min_eod = eod
            min_eod_date = d
        if eod < 0 and first_breach is None:
            first_breach = d
        if eod < warning_threshold and first_warning is None:
            first_warning = d
        daily.append(
            {
                "date": d,
                "flows": day_flows,
                "flow_sum": day_sum,
                "eod": eod,
                "negative": eod < 0,
                "warning": eod < warning_threshold,
            }
        )

    months = month_metrics(daily, warning_threshold)
    year_summaries = _year_summaries(daily, start_date, end_date, warning_threshold)

    return {
        "daily": daily,
        "months": months,
        "years": year_summaries,
        "summary": {
            "start_date": start_date,
            "end_date": end_date,
            "start_balance": float(start_balance),
            "ending_balance": daily[-1]["eod"] if daily else float(start_balance),
            "min_eod": min_eod,
            "min_eod_date": min_eod_date,
            "first_breach": first_breach,
            "first_warning": first_warning,
            "negative_days": sum(1 for x in daily if x["negative"]),
            "warning_days": sum(1 for x in daily if x["warning"]),
            "warning_threshold": warning_threshold,
        },
    }


def month_metrics(daily: list[dict], warning_threshold: float = 100.0) -> list[dict]:
    """Aggregate daily EOD into per-month dashboard rows."""
    if not daily:
        return []
    buckets: dict[tuple[int, int], list] = {}
    for row in daily:
        d = row["date"]
        buckets.setdefault((d.year, d.month), []).append(row)

    out = []
    for (y, m) in sorted(buckets):
        rows = buckets[(y, m)]
        eods = [r["eod"] for r in rows]
        neg = sum(1 for e in eods if e < 0)
        warn = sum(1 for e in eods if e < warning_threshold)
        out.append(
            {
                "year": y,
                "month": m,
                "label": f"{y}-{m:02d}",
                "month_end": eods[-1],
                "days_negative": neg,
                "days_warning": warn,
                "min_eod": min(eods),
                "max_eod": max(eods),
                "first_breach": next((r["date"] for r in rows if r["eod"] < 0), None),
                "days_in_month": len(rows),
            }
        )
    return out


def _flow_as_dict(f: Flow) -> dict:
    return {
        "date": f.date,
        "amount": float(f.amount),
        "category": f.category,
        "label": f.label or f.category,
        "source": f.source,
    }


def _fmt_money_plain(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


_FLEXIBLE_OUTFLOW_KEYWORDS = ("savings", "allowance", "wifes", "wife")


def breach_autopsy(
    daily: list[dict],
    year: Optional[int] = None,
    month: Optional[int] = None,
    *,
    breach_date: Optional[date] = None,
) -> Optional[dict]:
    """Pinpoint what drove a month's first negative EOD (or a given breach date).

    Returns None when there is no negative day in scope. Payload includes
    prior EOD, that day's flows (most-negative first), largest outflows,
    next inflow if any, a plain-English cause_summary, and an optional
    light suggestion when flexible outflows land just before a paycheck.
    """
    if not daily:
        return None

    by_date: dict[date, dict] = {row["date"]: row for row in daily}
    ordered = sorted(by_date)

    if breach_date is not None:
        bd = breach_date if isinstance(breach_date, date) else _parse_date(breach_date)
        row = by_date.get(bd)
        if row is None or row["eod"] >= 0:
            return None
        first = bd
    else:
        if year is None or month is None:
            raise ValueError("breach_autopsy requires year+month or breach_date")
        month_rows = [
            r for r in daily if r["date"].year == int(year) and r["date"].month == int(month)
        ]
        first = next((r["date"] for r in month_rows if r["eod"] < 0), None)
        if first is None:
            return None

    breach_row = by_date[first]
    idx = ordered.index(first)
    if idx > 0:
        prior_date = ordered[idx - 1]
        prior_eod = float(by_date[prior_date]["eod"])
    else:
        prior_date = None
        prior_eod = float(breach_row["eod"] - breach_row["flow_sum"])

    flows_sorted = sorted(breach_row.get("flows") or [], key=lambda f: (f.amount, f.category))
    flow_dicts = [_flow_as_dict(f) for f in flows_sorted]
    outflows = [fd for fd in flow_dicts if fd["amount"] < 0]
    largest_outflows = outflows[:5]

    next_inflow = None
    for d in ordered[idx + 1 :]:
        row = by_date[d]
        pos = [f for f in (row.get("flows") or []) if f.amount > 0]
        if not pos:
            continue
        top = max(pos, key=lambda f: f.amount)
        next_inflow = {
            "date": d,
            "amount": float(top.amount),
            "category": top.category,
            "label": top.label or top.category,
            "day_flow_sum": float(row["flow_sum"]),
            "eod": float(row["eod"]),
            "days_after": (d - first).days,
        }
        break

    top_bits = [
        f"{fd['category']} ({_fmt_money_plain(fd['amount'])})" for fd in largest_outflows[:3]
    ]
    cause = (
        f"On {first.isoformat()}, EOD fell from {_fmt_money_plain(prior_eod)} to "
        f"{_fmt_money_plain(float(breach_row['eod']))}"
    )
    if top_bits:
        cause += " primarily from " + ", ".join(top_bits)
    cause += "."
    if next_inflow:
        cause += (
            f" Recovered on {next_inflow['date'].isoformat()} when "
            f"{next_inflow['category']} ({_fmt_money_plain(next_inflow['amount'])}) landed "
            f"(EOD {_fmt_money_plain(next_inflow['eod'])})."
        )

    suggestion = None
    flexible = [
        fd
        for fd in largest_outflows
        if any(
            k in f"{fd['category']} {fd.get('label') or ''}".lower()
            for k in _FLEXIBLE_OUTFLOW_KEYWORDS
        )
    ]
    if (
        flexible
        and next_inflow
        and next_inflow["days_after"] <= 2
        and next_inflow["amount"] >= 1000
    ):
        flex_names = ", ".join(dict.fromkeys(fd["category"] for fd in flexible))
        when = (
            "the day before"
            if next_inflow["days_after"] == 1
            else f"{next_inflow['days_after']} days before"
        )
        suggestion = (
            f"Large flexible outflows ({flex_names}) landed {when} "
            f"{next_inflow['category']} — consider moving them after payday "
            f"or requesting Jordan pay earlier."
        )

    return {
        "first_breach": first,
        "prior_date": prior_date,
        "prior_eod": prior_eod,
        "breach_eod": float(breach_row["eod"]),
        "flow_sum": float(breach_row["flow_sum"]),
        "flows": flow_dicts,
        "largest_outflows": largest_outflows,
        "next_inflow": next_inflow,
        "cause_summary": cause,
        "suggestion": suggestion,
        "year": first.year,
        "month": first.month,
    }



_MONTH_ABBR = (
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def pitfall_months_by_year(
    months: list[dict], *, key: str = "days_negative"
) -> dict[int, list[str]]:
    """Map year → month abbreviations where the given day-count key is > 0.

    ``key`` is typically ``days_negative`` (EOD < $0) or ``days_warning``.
    Years with no pitfalls still appear with an empty list when present in ``months``.
    """
    out: dict[int, list[str]] = {}
    for m in months:
        y = int(m["year"])
        out.setdefault(y, [])
        if (m.get(key) or 0) > 0:
            out[y].append(_MONTH_ABBR[int(m["month"])])
    return out


def format_pitfall_ribbon(
    months: list[dict],
    *,
    key: str = "days_negative",
    years: Optional[Iterable[int]] = None,
) -> str:
    """Human ribbon like ``2026: Dec · 2027: Jan, Jun · 2028: none``."""
    by = pitfall_months_by_year(months, key=key)
    if years is None:
        years = sorted(by.keys())
    else:
        years = list(years)
    parts = []
    for y in years:
        labels = by.get(int(y), [])
        parts.append(f"{y}: {', '.join(labels) if labels else 'none'}")
    return " · ".join(parts)


def year_pitfall_scorecard(
    months: list[dict],
    *,
    key: str = "days_negative",
    years: Optional[Iterable[int]] = None,
) -> list[dict]:
    """Pictorial year scorecard rows matching ``format_pitfall_ribbon`` logic.

    Each entry: year, is_bad, bad_months (abbr list), red_month_count, detail
    ("All clear" or "Dec" / "Jan, Jun").
    A year is bad when it has any month with the given day-count key > 0
    (default ``days_negative`` — same as the classic pitfall ribbon).
    """
    by = pitfall_months_by_year(months, key=key)
    if years is None:
        years = sorted(by.keys())
    else:
        years = list(years)
    out: list[dict] = []
    for y in years:
        labels = list(by.get(int(y), []))
        is_bad = bool(labels)
        out.append(
            {
                "year": int(y),
                "is_bad": is_bad,
                "bad_months": labels,
                "red_month_count": len(labels),
                "detail": ", ".join(labels) if labels else "All clear",
            }
        )
    return out


def filter_months_for_year(months: list[dict], year: Optional[int]) -> list[dict]:
    """Return months for ``year``, or all months when ``year`` is None (All)."""
    if year is None:
        return list(months)
    return [m for m in months if int(m["year"]) == int(year)]


def year_scorecard_kpis(months: list[dict]) -> dict:
    """Min EOD / red-month count / ending balance for a filtered month list."""
    if not months:
        return {
            "min_eod": None,
            "red_months": 0,
            "ending_balance": None,
            "negative_days": 0,
            "warning_days": 0,
            "first_breach": None,
        }
    return {
        "min_eod": min(m["min_eod"] for m in months),
        "red_months": sum(1 for m in months if (m.get("days_negative") or 0) > 0),
        "ending_balance": months[-1]["month_end"],
        "negative_days": sum(m.get("days_negative") or 0 for m in months),
        "warning_days": sum(m.get("days_warning") or 0 for m in months),
        "first_breach": next(
            (m["first_breach"] for m in months if m.get("first_breach")), None
        ),
    }


def _year_summaries(daily: list[dict], start: date, end: date, warning_threshold: float) -> list[dict]:
    if not daily:
        return []
    by_year: dict[int, list] = {}
    for row in daily:
        by_year.setdefault(row["date"].year, []).append(row)
    out = []
    for y in sorted(by_year):
        rows = by_year[y]
        eods = [r["eod"] for r in rows]
        out.append(
            {
                "year": y,
                "ending_balance": eods[-1],
                "min_eod": min(eods),
                "min_eod_date": min(rows, key=lambda r: r["eod"])["date"],
                "negative_days": sum(1 for e in eods if e < 0),
                "warning_days": sum(1 for e in eods if e < warning_threshold),
                "first_breach": next((r["date"] for r in rows if r["eod"] < 0), None),
                "red_months": sum(
                    1
                    for (yy, mm), grp in _group_months(rows).items()
                    if any(r["eod"] < 0 for r in grp)
                ),
            }
        )
    return out


def _group_months(rows: list[dict]) -> dict:
    g = {}
    for r in rows:
        g.setdefault((r["date"].year, r["date"].month), []).append(r)
    return g


def compare_scenarios(
    start_date: date,
    end_date: date,
    start_balance: float,
    rules: list[dict],
    planned: list[dict],
    actuals: list[dict],
    scenarios: list[dict],
    warning_threshold: float = 100.0,
    suppress_rules_through: Optional[date] = None,
) -> list[dict]:
    """
    Run baseline + each named scenario.
    scenarios: [{id, name, deltas: [ScenarioDelta|dict]}, ...]
    Returns list of {name, summary, years, months} for comparison UI.
    """
    results = []
    # Baseline
    base = project(
        start_date,
        end_date,
        start_balance,
        rules,
        planned,
        actuals,
        None,
        warning_threshold,
        suppress_rules_through=suppress_rules_through,
    )
    results.append({"id": None, "name": "Baseline", "is_baseline": True, **_compact(base)})

    for sc in scenarios:
        deltas_raw = sc.get("deltas") or []
        deltas = [
            d if isinstance(d, ScenarioDelta) else ScenarioDelta.from_dict(d) for d in deltas_raw
        ]
        res = project(
            start_date,
            end_date,
            start_balance,
            rules,
            planned,
            actuals,
            deltas,
            warning_threshold,
            suppress_rules_through=suppress_rules_through,
        )
        results.append(
            {
                "id": sc.get("id"),
                "name": sc.get("name") or "Scenario",
                "is_baseline": False,
                "description": sc.get("description") or "",
                **_compact(res),
            }
        )
    return results


def _compact(res: dict) -> dict:
    return {
        "summary": res["summary"],
        "years": res["years"],
        "months": res["months"],
    }
