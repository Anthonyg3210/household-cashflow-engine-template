"""Variable bill amounts from Chase actuals (Forecast CONVERGE change set C).

Computes 3/6/12-mo averages, 12-mo median, same-month last year, then picks:
  - 3 good months → THIN (3-mo avg)
  - 6 usable; 12 preferred baseline
  - last-3 avg >15% off 12-mo → recent regime (use 3-mo)
  - same-month LY >20% off 12-mo → seasonal $ for that calendar month
  - step-change sticky 2+ months → FIXED new level Y

REPLACE rule amounts in expand_rules for override categories (FPL) on dates
>= VARIABLE_APPLY_FROM. Never add on top of Excel (no double count).
Sep stays under suppress_rules_through / Excel bootstrap.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

VARIABLE_APPLY_FROM = date(2026, 10, 1)

# Method-driven REPLACE in expand_rules (HOW MUCH only; WHO/WHEN unchanged).
VARIABLE_OVERRIDE_CATEGORIES = frozenset({"FPL"})

# Labeled variable in catalog/UI but keep recurring_rules amount.
VARIABLE_LABEL_ONLY_CATEGORIES = frozenset({"Water", "Gas Bill"})

VARIABLE_UI_CATEGORIES = VARIABLE_OVERRIDE_CATEGORIES | VARIABLE_LABEL_ONLY_CATEGORIES

_CHASE_SOURCE = "bank_csv"
_MIN_GOOD_ABS = 20.0  # ignore tiny fee-only / noise months
_RECENT_REGIME_PCT = 0.15
_SEASONAL_PCT = 0.20
_STEP_CHANGE_PCT = 0.20


@dataclass
class VariablePlan:
    category: str
    n_good: int = 0
    avg3: Optional[float] = None
    avg6: Optional[float] = None
    avg12: Optional[float] = None
    med12: Optional[float] = None
    last_actual: Optional[float] = None
    last_actual_month: Optional[str] = None
    baseline: Optional[float] = None
    baseline_method: str = "none"
    recent_regime: bool = False
    step_fixed: Optional[float] = None
    # calendar month 1..12 → same-month last-year abs amount (when seasonal)
    seasonal_by_month: dict[int, float] = field(default_factory=dict)
    monthly_abs: dict[str, float] = field(default_factory=dict)  # YYYY-MM → abs

    def amount_for(self, d: date) -> tuple[float, str]:
        """Return (absolute dollars, method label) for a projection date."""
        if self.step_fixed is not None and not self.recent_regime:
            return float(self.step_fixed), "FIXED step-change"
        if self.recent_regime and self.avg3 is not None:
            return float(self.avg3), "recent regime (3-mo avg)"
        seasonal = self.seasonal_by_month.get(d.month)
        if seasonal is not None:
            return float(seasonal), f"seasonal (same-month LY)"
        if self.baseline is not None:
            return float(self.baseline), self.baseline_method
        return 0.0, "none"

    def ui_dict(self, forecast_abs: Optional[float] = None, *, keep_rule: bool = False) -> dict:
        method = self.baseline_method
        if keep_rule:
            method = "rule amount (variable class)"
        elif self.recent_regime and self.avg3 is not None:
            method = "recent regime (3-mo avg)"
        elif self.step_fixed is not None:
            method = "FIXED step-change"
        fc = forecast_abs
        if fc is None and not keep_rule:
            # near-term default (Oct+)
            fc, method = self.amount_for(VARIABLE_APPLY_FROM)
        return {
            "category": self.category,
            "forecast": float(fc) if fc is not None else None,
            "method": method,
            "last_actual": self.last_actual,
            "last_actual_month": self.last_actual_month,
            "avg3": self.avg3,
            "avg6": self.avg6,
            "avg12": self.avg12,
            "med12": self.med12,
            "seasonal": dict(self.seasonal_by_month),
            "n_good": self.n_good,
            "recent_regime": self.recent_regime,
        }


def _parse_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _monthly_abs_totals(
    actuals: Iterable[dict],
    category: str,
    *,
    source: str = _CHASE_SOURCE,
) -> dict[str, float]:
    """Sum Chase actuals per YYYY-MM for a category (signed→absolute magnitude)."""
    buckets: dict[str, float] = {}
    cat_l = (category or "").strip().lower()
    for a in actuals or []:
        if (a.get("source") or "") != source:
            continue
        if a.get("enabled", True) is False:
            continue
        if (a.get("category") or "").strip().lower() != cat_l:
            continue
        d = _parse_date(a.get("date"))
        if d is None:
            continue
        buckets[_month_key(d)] = buckets.get(_month_key(d), 0.0) + float(a.get("amount") or 0.0)
    # store absolute bill size (expenses are negative in twin)
    return {k: abs(v) for k, v in buckets.items() if abs(v) >= _MIN_GOOD_ABS}


def _avg(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def _pct_off(a: float, b: float) -> float:
    if b == 0:
        return 0.0 if a == 0 else 1.0
    return abs(a - b) / abs(b)


def build_plan(category: str, actuals: Iterable[dict], *, as_of: Optional[date] = None) -> VariablePlan:
    """Build a VariablePlan from Chase actuals for one category."""
    monthly = _monthly_abs_totals(actuals, category)
    plan = VariablePlan(category=category, monthly_abs=dict(monthly))
    if not monthly:
        return plan

    keys = sorted(monthly.keys())
    plan.n_good = len(keys)
    plan.last_actual_month = keys[-1]
    plan.last_actual = monthly[keys[-1]]

    last3 = [monthly[k] for k in keys[-3:]]
    last6 = [monthly[k] for k in keys[-6:]]
    last12 = [monthly[k] for k in keys[-12:]]
    plan.avg3 = _avg(last3) if len(last3) >= 3 else (_avg(last3) if last3 else None)
    plan.avg6 = _avg(last6) if len(last6) >= 6 else None
    plan.avg12 = _avg(last12) if len(last12) >= 12 else None
    plan.med12 = float(statistics.median(last12)) if len(last12) >= 12 else None

    # Baseline preference: 12 → 6 → 3 (thin)
    if plan.avg12 is not None:
        plan.baseline = plan.avg12
        plan.baseline_method = "12-mo avg"
    elif plan.avg6 is not None:
        plan.baseline = plan.avg6
        plan.baseline_method = "6-mo avg"
    elif plan.avg3 is not None or (plan.avg3 is None and last3):
        plan.avg3 = plan.avg3 or _avg(last3)
        plan.baseline = plan.avg3
        plan.baseline_method = "THIN 3-mo avg"
    else:
        plan.baseline = plan.last_actual
        plan.baseline_method = "last actual"

    # Recent regime: last3 >15% off 12-mo
    if plan.avg3 is not None and plan.avg12 is not None:
        if _pct_off(plan.avg3, plan.avg12) > _RECENT_REGIME_PCT:
            plan.recent_regime = True

    # Seasonal: same-month LY >20% off 12-mo → store for that calendar month
    if plan.avg12 is not None:
        ref = as_of or date.today()
        for m in range(1, 13):
            ly = date(ref.year - 1, m, 1)
            # Prefer LY relative to latest actual year when possible
            if keys:
                latest_y = int(keys[-1][:4])
                ly_key = f"{latest_y - 1}-{m:02d}"
            else:
                ly_key = _month_key(ly)
            # also try calendar LY from as_of
            candidates = [ly_key, f"{ref.year - 1}-{m:02d}"]
            ly_amt = next((monthly[k] for k in candidates if k in monthly), None)
            if ly_amt is None:
                continue
            if _pct_off(ly_amt, plan.avg12) > _SEASONAL_PCT:
                plan.seasonal_by_month[m] = float(ly_amt)

    # Step-change sticky 2+: last 2+ months each >20% off prior baseline (ex-those months)
    if len(keys) >= 4:
        sticky = keys[-2:]
        prior_keys = keys[:-2]
        prior_vals = [monthly[k] for k in prior_keys[-12:]]
        prior_avg = _avg(prior_vals)
        if prior_avg and all(_pct_off(monthly[k], prior_avg) > _STEP_CHANGE_PCT for k in sticky):
            # require consecutive sticky months on the same side of prior
            signs = [(monthly[k] - prior_avg) for k in sticky]
            if all(s > 0 for s in signs) or all(s < 0 for s in signs):
                plan.step_fixed = _avg([monthly[k] for k in sticky])

    return plan


def build_plans(
    actuals: Iterable[dict],
    categories: Optional[Iterable[str]] = None,
    *,
    as_of: Optional[date] = None,
) -> dict[str, VariablePlan]:
    cats = list(categories) if categories is not None else sorted(VARIABLE_UI_CATEGORIES)
    return {c: build_plan(c, actuals, as_of=as_of) for c in cats}


def override_categories_from_catalog(catalog: Optional[dict] = None) -> frozenset[str]:
    """Categories with amount_class=variable that should REPLACE rule $ (not label-only)."""
    # Default: FPL overrides; Water is label-only unless catalog says otherwise.
    if not catalog:
        return VARIABLE_OVERRIDE_CATEGORIES
    out = set()
    for it in (catalog.get("essentials") or []):
        if not isinstance(it, dict):
            continue
        if (it.get("amount_class") or "").lower() != "variable":
            continue
        if it.get("apply_variable_method", None) is False:
            continue
        name = (it.get("name") or it.get("id") or "").strip()
        # Map essential names to recurring rule categories
        if name.upper() == "FPL" or (it.get("id") or "") == "fpl":
            if it.get("apply_variable_method", True) is not False:
                out.add("FPL")
        elif name.lower() == "water" or (it.get("id") or "") == "water":
            # Water: variable class, keep rule amount unless explicitly enabled
            if it.get("apply_variable_method") is True:
                out.add("Water")
        elif name.lower() in ("gas bill", "gas") or (it.get("id") or "") == "gas":
            # Gas Bill: variable class, keep rule amount unless explicitly enabled
            if it.get("apply_variable_method") is True:
                out.add("Gas Bill")
    return frozenset(out) if out else VARIABLE_OVERRIDE_CATEGORIES


def apply_variable_override(
    category: str,
    d: date,
    rule_amount: float,
    *,
    plans: Optional[dict[str, VariablePlan]] = None,
    actuals: Optional[Iterable[dict]] = None,
    override_categories: Optional[frozenset[str]] = None,
) -> float:
    """REPLACE rule amount with variable method when applicable; else return rule_amount."""
    if d < VARIABLE_APPLY_FROM:
        return float(rule_amount)
    cats = override_categories or VARIABLE_OVERRIDE_CATEGORIES
    if category not in cats:
        return float(rule_amount)
    plan = None
    if plans and category in plans:
        plan = plans[category]
    elif actuals is not None:
        plan = build_plan(category, actuals)
    if plan is None or plan.n_good == 0:
        return float(rule_amount)
    abs_amt, _method = plan.amount_for(d)
    if abs_amt <= 0:
        return float(rule_amount)
    # Preserve expense/income sign from the rule
    if float(rule_amount) < 0:
        return -abs(abs_amt)
    if float(rule_amount) > 0:
        return abs(abs_amt)
    return -abs(abs_amt)


def _fmt_dollars(x) -> str:
    """Money for UI copy: $1,234.56 (or —)."""
    if x is None:
        return "—"
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "—"


def format_ui_line(row: dict) -> str:
    """Forecast $X · method · last actual · 12-mo avg (legacy compact line)."""
    fc_s = _fmt_dollars(row.get("forecast"))
    method = row.get("method") or "—"
    la_s = _fmt_dollars(row.get("last_actual"))
    a12_s = _fmt_dollars(row.get("avg12"))
    return f"Forecast {fc_s} · {method} · last actual {la_s} · 12-mo avg {a12_s}"


def plain_english_variable_sentence(row: dict) -> str:
    """One partner-friendly sentence explaining the planning amount (math unchanged)."""
    method = (row.get("method") or "").strip()
    cat = (row.get("category") or "").strip()
    fc_s = _fmt_dollars(row.get("forecast"))
    la = row.get("last_actual")
    la_s = _fmt_dollars(la)
    a12 = row.get("avg12")
    a12_s = _fmt_dollars(a12)

    if "recent regime" in method:
        if cat == "FPL":
            bill_word = "electric"
        elif cat == "Gas Bill":
            bill_word = "gas"
        else:
            bill_word = "utility"
        parts = [f"Using your last 3 {bill_word} bills (they've been higher lately)."]
        if la is not None:
            parts.append(f"Last bill was {la_s}.")
        if a12 is not None:
            parts.append(f"A full-year average would be about {a12_s}.")
        return " ".join(parts)

    if "rule amount" in method:
        if cat == "Gas Bill":
            parts = [
                f"Gas usage varies month to month, but {fc_s} is your typical bill (12-mo median) — left as-is."
            ]
        else:
            parts = [
                f"Amount can vary month to month, but {fc_s} still matches what you usually pay — left as-is."
            ]
        if la is not None:
            parts.append(f"Last bill was {la_s}.")
        return " ".join(parts)

    if method == "12-mo avg":
        parts = [f"Using your typical full-year average ({a12_s})."]
        if la is not None:
            parts.append(f"Last bill was {la_s}.")
        return " ".join(parts)

    if method == "6-mo avg":
        a6 = _fmt_dollars(row.get("avg6"))
        parts = [f"Using your last 6 months' average (about {a6})."]
        if la is not None:
            parts.append(f"Last bill was {la_s}.")
        return " ".join(parts)

    if "THIN" in method:
        a3 = _fmt_dollars(row.get("avg3"))
        parts = [
            f"Only a few recent bills on file — planning from those (about {a3})."
        ]
        if la is not None:
            parts.append(f"Last bill was {la_s}.")
        return " ".join(parts)

    if "FIXED step-change" in method:
        parts = [
            f"Bills stepped up to a new level — planning {fc_s} going forward."
        ]
        if la is not None:
            parts.append(f"Last bill was {la_s}.")
        return " ".join(parts)

    if "seasonal" in method:
        parts = [
            f"This month often runs different than the yearly average — planning {fc_s}."
        ]
        if la is not None:
            parts.append(f"Last bill was {la_s}.")
        return " ".join(parts)

    if method == "last actual":
        parts = [f"Planning from your most recent bill ({la_s})."]
        return " ".join(parts)

    # Fallback — still plain, no method jargon on the face
    parts = [f"Planning {fc_s} from your recent bills."]
    if la is not None:
        parts.append(f"Last bill was {la_s}.")
    return " ".join(parts)


def plain_english_variable_detail_lines(row: dict) -> list[str]:
    """Collapsed 'More detail' technical stats (kept off the face)."""
    from calendar import month_abbr

    lines: list[str] = []
    method = row.get("method") or "—"
    lines.append(f"Method label (engine): {method}")
    if row.get("med12") is not None:
        lines.append(f"12-mo median: {_fmt_dollars(row['med12'])}")
    if row.get("avg3") is not None:
        lines.append(f"3-mo average: {_fmt_dollars(row['avg3'])}")
    if row.get("avg6") is not None:
        lines.append(f"6-mo average: {_fmt_dollars(row['avg6'])}")
    if row.get("avg12") is not None:
        lines.append(f"12-mo average: {_fmt_dollars(row['avg12'])}")
    seasonal = row.get("seasonal") or {}
    if seasonal:
        sm = ", ".join(
            f"{month_abbr[m]} {_fmt_dollars(v)}" for m, v in sorted(seasonal.items())
        )
        lines.append(f"Seasonal months: {sm}")
    if row.get("last_actual_month"):
        lines.append(f"Last actual month: {row['last_actual_month']}")
    if row.get("n_good") is not None:
        lines.append(f"Good history months: {row['n_good']}")
    return lines


def oct_plus_fpl_water_totals(
    rules: Iterable[dict],
    actuals: Iterable[dict],
    start: date,
    end: date,
    *,
    suppress_rules_through: Optional[date] = None,
) -> dict:
    """Compare old initiated FPL+Water+Gas vs new model $ over Oct+ horizon."""
    from .project import expand_rules  # local import avoids cycle at module load

    _util_cats = ("FPL", "Water", "Gas Bill")
    rules_list = [r for r in rules if (r.get("category") in _util_cats and r.get("enabled", True))]
    win_start = max(start, VARIABLE_APPLY_FROM)
    if suppress_rules_through and win_start <= suppress_rules_through:
        win_start = suppress_rules_through + __import__("datetime").timedelta(days=1)
    if win_start > end:
        return {
            "old_initiated": 0.0,
            "new_model": 0.0,
            "delta": 0.0,
            "start": win_start,
            "end": end,
        }

    old_flows = expand_rules(
        rules_list,
        win_start,
        end,
        suppress_rules_through=suppress_rules_through,
        actuals=None,
        apply_variable=False,
    )
    new_flows = expand_rules(
        rules_list,
        win_start,
        end,
        suppress_rules_through=suppress_rules_through,
        actuals=actuals,
        apply_variable=True,
    )
    old_sum = sum(abs(f.amount) for f in old_flows)
    new_sum = sum(abs(f.amount) for f in new_flows)
    return {
        "old_initiated": old_sum,
        "new_model": new_sum,
        "delta": new_sum - old_sum,
        "start": win_start,
        "end": end,
        "old_count": len(old_flows),
        "new_count": len(new_flows),
    }


def variable_ui_rows(
    actuals: Iterable[dict],
    rules: Iterable[dict],
    *,
    as_of: Optional[date] = None,
) -> list[dict]:
    """UI rows for FPL (method) and Water/Gas Bill (keep rule $)."""
    plans = build_plans(actuals, VARIABLE_UI_CATEGORIES, as_of=as_of)
    rows = []
    # Rule amounts (absolute) for Water/Gas keep / FPL display fallback
    rule_abs: dict[str, float] = {}
    for r in rules or []:
        if not r.get("enabled", True):
            continue
        cat = r.get("category") or ""
        if cat not in VARIABLE_UI_CATEGORIES:
            continue
        # Prefer near-term (pre-2028) stamp when split
        start_s = r.get("start_date") or ""
        if cat in rule_abs and start_s >= "2028-01-01":
            continue
        rule_abs[cat] = abs(float(r.get("amount") or 0))

    for cat in ("FPL", "Water", "Gas Bill"):
        if cat not in VARIABLE_UI_CATEGORIES:
            continue
        plan = plans.get(cat) or VariablePlan(category=cat)
        keep = cat in VARIABLE_LABEL_ONLY_CATEGORIES
        if keep:
            fc = rule_abs.get(cat)
            row = plan.ui_dict(fc, keep_rule=True)
        else:
            fc, method = plan.amount_for(VARIABLE_APPLY_FROM) if plan.n_good else (rule_abs.get(cat), "rule amount")
            row = plan.ui_dict(fc)
            if plan.n_good:
                row["method"] = method
        rows.append(row)
    return rows
