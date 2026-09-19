"""Income / expense analytics helpers for Household spending & income insights page.

Uses bank_csv actuals for history and projection daily flows for forecast.
Does not mutate start_balance or rules.
"""
from __future__ import annotations

import html
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

# Intended end of Jordan side gig / secondary Other Income in the plan
SIDE_GIG_PLAN_END = date(2027, 2, 28)  # through 2027-02
SIDE_GIG_PLAN_END_MONTH = "2027-02"

# Jordan primary ($1500/mo) OK through 2027; Excel blank / twin amount_by_year 2028=0
SECONDARY_SUNSET = date(2027, 12, 31)  # last OK operating month
SECONDARY_SUNSET_MONTH = "2027-12"
# From 2028-01 onward, Jordan primary in operating cash is a dependency flag

STREAM_PRIMARY = "Alex primary"
STREAM_SECONDARY = "Jordan primary (sunset 2028)"
STREAM_SIDE_GIG = "Jordan secondary (side_gig)"
STREAM_OTHER = "Other / gifts / discretionary"

STREAM_ORDER = [
    STREAM_PRIMARY,
    STREAM_SECONDARY,
    STREAM_SIDE_GIG,
    STREAM_OTHER,
]

STREAM_SHORT = {
    STREAM_PRIMARY: "Alex",
    STREAM_SECONDARY: "Jordan primary",
    STREAM_SIDE_GIG: "Jordan secondary",
    STREAM_OTHER: "Other / gifts",
}

# Expense parents preferred chart order (taxonomy v2)
EXPENSE_PARENT_ORDER = [
    "Housing",
    "Utilities",
    "Groceries",
    "Dining",
    "Shopping",
    "Credit Cards",
    "Auto",
    "Transportation",
    "School",
    "Insurance",
    "Debt",
    "Home Services & Subs",
    "Entertainment",
    "Health",
    "Transfers / Savings",
    "Work Wash",
]

# Featured parents for Insights subcategory breakouts (UI defaults)
FEATURED_EXPENSE_PARENTS = [
    "Utilities",
    "Groceries",
    "Dining",
    "Housing",
    "Shopping",
]


def _parse_date(d: Any) -> date | None:
    if d is None:
        return None
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    s = str(d)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"



def _flow_get(f: Any, key: str, default=None):
    """Read Flow dataclass or dict uniformly."""
    if isinstance(f, dict):
        return f.get(key, default)
    return getattr(f, key, default)


def _is_secondary_primary_deposit(label: str | None, amount: float) -> bool:
    """bank check/ATM deposits that are Jordan's ~$1,500/mo primary paycheck.

    Bank CSV has no employer name — only ATM CHECK DEPOSIT / DEPOSIT ID NUMBER —
    so import defaults them to Other Income. Detect by deposit-like memo + amount
    band covering exact $1,500 and occasional same-deposit extras (~$1.4k–$2.2k).
    """
    lab_u = (label or "").upper()
    amt = float(amount or 0)
    if not (1400.0 <= amt <= 2200.0):
        return False
    deposit_hints = (
        "ATM CHECK DEPOSIT",
        "ATM CASH DEPOSIT",
        "DEPOSIT  ID NUMBER",
        "DEPOSIT ID NUMBER",
        "CHECK - ",  # pending/bank CHECK at branch
    )
    if any(h in lab_u for h in deposit_hints):
        return True
    # Explicit Jordan primary labels (pending itemization / manual)
    low = (label or "").lower()
    if "jordan" in low and ("income" in low or "paycheck" in low or "sep income" in low):
        return True
    return False


def classify_income_stream(
    category: str | None,
    label: str | None = "",
    amount: float = 0.0,
) -> str | None:
    """Map a positive inflow to one of the four insight streams, or None if not income."""
    cat = (category or "").strip()
    lab_u = (label or "").upper()
    amt = float(amount or 0)
    low = (label or "").lower()

    if amt <= 0 and "income" not in cat.lower():
        # Classification is for inflows; allow explicit income cats even if amount unknown
        pass

    if cat == "Alex's Income" or "NORTHSTAR" in lab_u:
        return STREAM_PRIMARY

    # BrightStart payroll / dir dep = side_gig secondary (CSV often tags as Jordan's Income)
    if "BRIGHTSTART" in lab_u and ("PAYROLL" in lab_u or "DIR DEP" in lab_u):
        return STREAM_SIDE_GIG

    # Jordan primary check deposits mis-tagged Other Income by merchant map
    if _is_secondary_primary_deposit(label, amt):
        return STREAM_SECONDARY

    if cat == "Jordan's Income":
        return STREAM_SECONDARY

    if cat == "Other Income":
        # Bonuses / birthday / explicit gifts stay Other even in side_gig $ band
        if any(k in low for k in ("bonus", "birthday", "gift")):
            return STREAM_OTHER
        # Plan side_gig stamps ≈ $600; gifts / discretionary otherwise
        if 450.0 <= amt <= 800.0:
            return STREAM_SIDE_GIG
        if "side_gig" in low:
            return STREAM_SIDE_GIG
        return STREAM_OTHER

    if "income" in cat.lower():
        return STREAM_OTHER

    return None


def income_frame_from_actuals(actuals: Iterable[dict], *, source: str = "bank_csv") -> pd.DataFrame:
    """Positive bank_csv (or all) income actuals with stream + month + actual/forecast flag."""
    rows = []
    for a in actuals:
        if source and a.get("source") != source:
            continue
        amt = float(a.get("amount") or 0)
        if amt <= 0:
            continue
        stream = classify_income_stream(a.get("category"), a.get("label"), amt)
        if not stream:
            continue
        d = _parse_date(a.get("date"))
        if not d:
            continue
        rows.append(
            {
                "date": d,
                "month": _month_key(d),
                "amount": amt,
                "category": a.get("category") or "",
                "label": a.get("label") or "",
                "stream": stream,
                "origin": "actual",
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["date", "month", "amount", "category", "label", "stream", "origin"]
        )
    return pd.DataFrame(rows)


def income_frame_from_projection(
    daily: list[dict],
    *,
    after: date | None = None,
) -> pd.DataFrame:
    """Forecast income rows from projection daily list (flows after `after`, default all)."""
    rows = []
    for day in daily:
        d = _parse_date(day.get("date"))
        if not d:
            continue
        if after is not None and d <= after:
            continue
        for f in day.get("flows") or []:
            amt = float(_flow_get(f, "amount") or 0)
            if amt <= 0:
                continue
            cat = _flow_get(f, "category") or ""
            label = _flow_get(f, "label") or ""
            stream = classify_income_stream(cat, label, amt)
            if not stream:
                continue
            rows.append(
                {
                    "date": d,
                    "month": _month_key(d),
                    "amount": amt,
                    "category": cat,
                    "label": label,
                    "stream": stream,
                    "origin": "forecast",
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["date", "month", "amount", "category", "label", "stream", "origin"]
        )
    return pd.DataFrame(rows)


def combine_income_history_forecast(
    actuals_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
) -> pd.DataFrame:
    """Prefer actual months; append forecast months not already covered by actuals."""
    if actuals_df is None or actuals_df.empty:
        out = forecast_df.copy() if forecast_df is not None else pd.DataFrame()
    elif forecast_df is None or forecast_df.empty:
        out = actuals_df.copy()
    else:
        actual_months = set(actuals_df["month"].unique())
        fwd = forecast_df[~forecast_df["month"].isin(actual_months)]
        out = pd.concat([actuals_df, fwd], ignore_index=True)
    if out.empty:
        return out
    return out.sort_values(["date", "stream"]).reset_index(drop=True)


def monthly_income_by_stream(idf: pd.DataFrame) -> pd.DataFrame:
    """Wide month × stream totals + origin label (actual / forecast / mixed)."""
    if idf is None or idf.empty:
        return pd.DataFrame()
    g = idf.groupby(["month", "stream"], as_index=False)["amount"].sum()
    wide = g.pivot(index="month", columns="stream", values="amount").fillna(0.0)
    for s in STREAM_ORDER:
        if s not in wide.columns:
            wide[s] = 0.0
    wide = wide[STREAM_ORDER]
    origin = (
        idf.groupby("month")["origin"]
        .agg(lambda s: "actual" if set(s) == {"actual"} else ("forecast" if set(s) == {"forecast"} else "mixed"))
    )
    wide["origin"] = origin.reindex(wide.index).fillna("actual")
    wide["total"] = wide[STREAM_ORDER].sum(axis=1)
    return wide.sort_index()


def income_mix_latest(monthly: pd.DataFrame) -> pd.DataFrame:
    """Pie-ready stream amounts for the latest month with any income."""
    if monthly is None or monthly.empty:
        return pd.DataFrame(columns=["stream", "amount"])
    # Prefer latest actual month if present
    actual_idx = monthly.index[monthly["origin"] == "actual"] if "origin" in monthly.columns else []
    if len(actual_idx):
        m = actual_idx[-1]
    else:
        m = monthly.index[-1]
    row = monthly.loc[m]
    rows = [{"stream": s, "amount": float(row[s]), "month": m} for s in STREAM_ORDER if float(row[s]) > 0]
    return pd.DataFrame(rows)



# ---------------------------------------------------------------------------
# Annual income focus (calendar year / YTD — not multi-year lumps)
# ---------------------------------------------------------------------------

_MONTH_ABBR = (
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


def month_key_label(month_key: str) -> str:
    """Human month label: '2026-08' → 'Aug 2026'."""
    try:
        y, m = int(month_key[:4]), int(month_key[5:7])
        return f"{_MONTH_ABBR[m]} {y}"
    except (TypeError, ValueError, IndexError):
        return str(month_key or "")


def month_key_short(month_key: str) -> str:
    """Short month: '2026-08' → 'Aug'."""
    try:
        m = int(month_key[5:7])
        return _MONTH_ABBR[m]
    except (TypeError, ValueError, IndexError):
        return str(month_key or "")


def month_range_plain(months: list[str] | None) -> str:
    """Plain range: ['2026-08','2026-09'] → 'Aug–Sep 2026'."""
    if not months:
        return ""
    ms = sorted(months)
    if len(ms) == 1:
        return month_key_label(ms[0])
    a, b = ms[0], ms[-1]
    try:
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
    except (TypeError, ValueError, IndexError):
        return f"{a} → {b}"
    if ya == yb:
        return f"{_MONTH_ABBR[ma]}–{_MONTH_ABBR[mb]} {ya}"
    return f"{_MONTH_ABBR[ma]} {ya}–{_MONTH_ABBR[mb]} {yb}"


_MONTH_FULL = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def month_label_long(month_key: str) -> str:
    """Human month label: '2026-08' → 'August 2026'."""
    try:
        y, m = int(month_key[:4]), int(month_key[5:7])
        return f"{_MONTH_FULL[m]} {y}"
    except (TypeError, ValueError, IndexError):
        return str(month_key or "")


def friendly_month_range(trailing_months: list[str] | None) -> str:
    """Trailing window: ['2026-07','2026-08','2026-09'] → 'Jul–Sep 2026'."""
    return month_range_plain(trailing_months)


def chart_label_amt_pct(name: str, amount: float, pct: float) -> str:
    """Legend / bar label: 'Alex: $4,966 (85%)'."""
    return f"{name}: ${float(amount):,.0f} ({float(pct):.0f}%)"


def annual_income_by_stream(
    idf: pd.DataFrame,
    year: int,
    *,
    origin: str | None = "actual",
) -> pd.DataFrame:
    """Calendar-year income totals by stream (not a multi-year lump sum).

    Prefer actuals when ``origin='actual'``. Returns columns:
      stream | short | amount | pct | year | months_present | label
    """
    cols = ["stream", "short", "amount", "pct", "year", "months_present", "label"]
    if idf is None or idf.empty:
        return pd.DataFrame(columns=cols)
    df = idf.copy()
    df["_year"] = df["date"].map(lambda d: d.year if isinstance(d, date) else _parse_date(d).year if _parse_date(d) else None)
    df = df[df["_year"] == int(year)]
    if origin and "origin" in df.columns:
        df = df[df["origin"] == origin]
    if df.empty:
        return pd.DataFrame(columns=cols)
    g = df.groupby("stream", as_index=False)["amount"].sum()
    months_map = df.groupby("stream")["month"].nunique().to_dict()
    total = float(g["amount"].sum())
    rows = []
    for s in STREAM_ORDER:
        hit = g.loc[g["stream"] == s, "amount"]
        amt = float(hit.iloc[0]) if len(hit) else 0.0
        pct = (100.0 * amt / total) if total > 0 else 0.0
        short = STREAM_SHORT.get(s, s)
        rows.append(
            {
                "stream": s,
                "short": short,
                "amount": amt,
                "pct": pct,
                "year": int(year),
                "months_present": int(months_map.get(s, 0)),
                "label": chart_label_amt_pct(short, amt, pct),
            }
        )
    return pd.DataFrame(rows)


def annualize_ytd(amount: float, year: int, as_of: date) -> float:
    """Annualize YTD: amount / months_elapsed * 12.

    ``months_elapsed`` is the calendar month count through ``as_of`` in ``year``
    (1–12). If ``as_of`` is before the year, returns 0; if after, treats as full 12.
    """
    amt = float(amount or 0.0)
    if as_of.year < int(year):
        return 0.0
    if as_of.year > int(year):
        months_elapsed = 12
    else:
        months_elapsed = max(1, min(12, int(as_of.month)))
    return amt / months_elapsed * 12.0


def income_yoy_comparison(
    idf: pd.DataFrame,
    this_year: int,
    last_year: int,
    *,
    as_of: date | None = None,
    origin: str | None = "actual",
) -> pd.DataFrame:
    """Side-by-side annual stream totals: last year actual, this YTD, run-rate.

    Columns: stream | short | last_year | this_ytd | this_run_rate | pct_this | label_this
    Caption-ready: not a 3-year total — annualized for comparison.
    """
    as_of = as_of or date.today()
    a = annual_income_by_stream(idf, last_year, origin=origin)
    b = annual_income_by_stream(idf, this_year, origin=origin)
    rows = []
    for s in STREAM_ORDER:
        short = STREAM_SHORT.get(s, s)
        last_amt = float(a.loc[a["stream"] == s, "amount"].sum()) if not a.empty else 0.0
        ytd = float(b.loc[b["stream"] == s, "amount"].sum()) if not b.empty else 0.0
        run = annualize_ytd(ytd, this_year, as_of)
        rows.append(
            {
                "stream": s,
                "short": short,
                "last_year": last_amt,
                "this_ytd": ytd,
                "this_run_rate": run,
                "last_year_col": int(last_year),
                "this_year_col": int(this_year),
            }
        )
    out = pd.DataFrame(rows)
    tot = float(out["this_ytd"].sum()) if not out.empty else 0.0
    if tot > 0:
        out["pct_this"] = 100.0 * out["this_ytd"] / tot
    else:
        out["pct_this"] = 0.0
    out["label_this"] = [
        chart_label_amt_pct(r["short"], r["this_ytd"], r["pct_this"]) for _, r in out.iterrows()
    ]
    return out


def income_mix_with_labels(mix: pd.DataFrame) -> pd.DataFrame:
    """Add pct + short + label columns to income_mix_latest output."""
    if mix is None or mix.empty:
        return pd.DataFrame(columns=["stream", "short", "amount", "pct", "month", "label"])
    out = mix.copy()
    total = float(out["amount"].sum())
    out["pct"] = (100.0 * out["amount"] / total) if total > 0 else 0.0
    out["short"] = out["stream"].map(lambda s: STREAM_SHORT.get(s, s))
    out["label"] = [
        chart_label_amt_pct(r["short"], r["amount"], r["pct"]) for _, r in out.iterrows()
    ]
    return out


# Must-pay / lights-on parents excluded from lifestyle discretionary chart.
# Credit Cards stay IN discretionary (lifestyle signal) except Student Loans category.
# School and Transfers / Savings are must-have / intentional save — excluded.
LIGHTS_ON_PARENTS = {
    "Housing",
    "Utilities",
    "Insurance",
    "Debt",
}
DISCRETIONARY_EXCLUDE_PARENTS = LIGHTS_ON_PARENTS | {
    "School",
    "Transfers / Savings",
}
# Categories always treated as must-pay debt even under Credit Cards parent
MUST_PAY_DEBT_CATEGORIES = {"Student Loans", "Other Debt"}


def discretionary_spend_by_parent(
    sdf: pd.DataFrame,
    months: list[str] | None = None,
    year: int | None = None,
    *,
    exclude_parents: set[str] | frozenset[str] | None = None,
) -> pd.DataFrame:
    """Lifestyle spend share by parent — beyond keeping the lights on.

    Excludes Housing / Utilities / Insurance / Debt / School / Transfers/Savings
    and Student Loans (even when parent is Credit Cards). Credit Cards (revolving
    lifestyle) remain in the mix.

    Returns: parent | amount | pct | label  (sorted by amount desc).
    """
    cols = ["parent", "amount", "pct", "label"]
    if sdf is None or sdf.empty:
        return pd.DataFrame(columns=cols)
    excl = set(exclude_parents) if exclude_parents is not None else set(DISCRETIONARY_EXCLUDE_PARENTS)
    df = sdf.copy()
    if year is not None:
        df = df[df["year"] == int(year)]
    if months is not None:
        df = df[df["month"].isin(months)]
    if df.empty:
        return pd.DataFrame(columns=cols)

    # Drop lights-on parents + must-pay debt categories (Student Loans under CC)
    mask_parent = ~df["parent"].isin(excl)
    cat = df["category"].fillna("").astype(str)
    sub = df["subcategory"].fillna("").astype(str)
    debt_cat = cat.isin(MUST_PAY_DEBT_CATEGORIES) | sub.isin(MUST_PAY_DEBT_CATEGORIES)
    df = df[mask_parent & ~debt_cat]
    if df.empty:
        return pd.DataFrame(columns=cols)

    g = df.groupby("parent", as_index=False)["spend"].sum().rename(columns={"spend": "amount"})
    total = float(g["amount"].sum())
    if total <= 0:
        return pd.DataFrame(columns=cols)
    g["pct"] = 100.0 * g["amount"] / total
    g["label"] = [
        chart_label_amt_pct(r["parent"], r["amount"], r["pct"]) for _, r in g.iterrows()
    ]
    # Featured / taxonomy order first, then by amount
    order_rank = {p: i for i, p in enumerate(EXPENSE_PARENT_ORDER)}
    g["_ord"] = g["parent"].map(lambda p: order_rank.get(p, 10_000))
    g = g.sort_values(["amount"], ascending=False).drop(columns=["_ord"])
    return g.reset_index(drop=True)


def preferred_mix_months(
    sdf: pd.DataFrame,
    parent: str,
    months: list[str] | None = None,
    *,
    n: int = 2,
    today: date | None = None,
) -> list[str]:
    """Up to n complete months (oldest→newest) for primary subcategory mix charts.

    Prefers months before the current calendar month so an in-progress month
    (e.g. only FPL posted in early September) does not dominate the mix bars.
    Falls back to latest months with parent spend when no prior complete month
    exists. Also drops a trailing month that looks thin vs the prior month
    (fewer distinct subcategories with spend) when a better prior month exists.
    """
    if sdf is None or sdf.empty or not parent or n <= 0:
        return []
    df = sdf[sdf["parent"] == parent].copy()
    if months:
        df = df[df["month"].isin(months)]
    if df.empty:
        return []
    # Months that actually have spend for this parent
    spend_by_m = (
        df.groupby("month", as_index=False)
        .agg(spend=("spend", "sum"), n_subs=("subcategory", "nunique"))
        .sort_values("month")
    )
    spend_by_m = spend_by_m[spend_by_m["spend"] > 0]
    if spend_by_m.empty:
        return []
    month_list = spend_by_m["month"].tolist()
    today = today or date.today()
    current = _month_key(today)
    complete = [m for m in month_list if m < current]
    candidates = complete if complete else list(month_list)

    # Thin trailing month heuristic (only when we have a prior in candidates)
    if len(candidates) >= 2:
        last = candidates[-1]
        prev = candidates[-2]
        n_last = int(spend_by_m.loc[spend_by_m["month"] == last, "n_subs"].iloc[0])
        n_prev = int(spend_by_m.loc[spend_by_m["month"] == prev, "n_subs"].iloc[0])
        # Incomplete if current calendar month, or clearly thinner than prior
        if last == current or (n_prev >= 3 and n_last <= max(1, n_prev // 2)):
            candidates = candidates[:-1]

    if not candidates:
        candidates = list(month_list)
    return candidates[-n:] if len(candidates) >= n else list(candidates)


def preferred_mix_month(
    sdf: pd.DataFrame,
    parent: str,
    months: list[str] | None = None,
    *,
    today: date | None = None,
) -> str | None:
    """Latest complete month for mix bars; else latest month with parent spend."""
    ms = preferred_mix_months(sdf, parent, months, n=1, today=today)
    return ms[-1] if ms else None


def latest_month_subcategory_mix(
    sdf: pd.DataFrame,
    parent: str,
    months: list[str] | None = None,
    *,
    today: date | None = None,
) -> tuple[pd.DataFrame, list[str], str | None, str | None]:
    """Primary subcategory mix = combined spend over last 2 complete months.

    Bars use window totals (% of those months combined) so an incomplete newest
    month (e.g. Sep with only FPL) does not make Utilities look FPL-only.
    MoM delta columns still compare the two complete months (latest vs prior).

    Returns (breakout_df, mix_months, m_cur, m_prev).
    """
    if sdf is None or sdf.empty or not parent:
        return pd.DataFrame(), [], None, None
    mix_months = preferred_mix_months(sdf, parent, months, n=2, today=today)
    if not mix_months:
        # Fall back to whatever months exist in the filter
        df = sdf[sdf["parent"] == parent].copy()
        if months:
            df = df[df["month"].isin(months)]
        mix_months = sorted(df["month"].unique())[-2:] if not df.empty else (
            sorted(months)[-2:] if months else []
        )
    if not mix_months:
        return pd.DataFrame(), [], None, None
    m_cur = mix_months[-1]
    m_prev = mix_months[-2] if len(mix_months) >= 2 else None
    brk = subcategory_breakout(sdf, parent, mix_months)
    if brk.empty:
        return brk, list(mix_months), m_cur, m_prev
    # Keep amount / pct_of_parent as the combined window sum from breakout
    out = brk.copy()
    parent_total = float(out["amount"].sum())
    out["parent_total"] = parent_total
    if parent_total > 0:
        out["pct_of_parent"] = 100.0 * out["amount"].astype(float) / parent_total
    out["label"] = [
        chart_label_amt_pct(r["subcategory"], r["amount"], r["pct_of_parent"])
        for _, r in out.iterrows()
    ]
    out = out.sort_values("amount", ascending=False).reset_index(drop=True)
    return out, list(mix_months), m_cur, m_prev



def subcategory_month_compare(
    sdf: pd.DataFrame,
    parent: str,
    months: list[str] | None = None,
    *,
    today: date | None = None,
) -> tuple[pd.DataFrame, str | None, str | None, str]:
    """Current vs prior month subcategory spend for grouped comparison bars.

    Uses the latest month in ``months`` (or in sdf for parent) as *current* and
    the previous calendar month with parent spend as *prior*. Incomplete current
    months are included (posted so far) with a caption noting progress.

    Returns (long_df, m_cur, m_prev, caption) where long_df columns are:
      subcategory, month, month_role (Prior|Current), spend, incomplete
    """
    empty = pd.DataFrame(
        columns=["subcategory", "month", "month_role", "spend", "incomplete"]
    )
    if sdf is None or sdf.empty or not parent:
        return empty, None, None, ""
    today = today or date.today()
    df = sdf[sdf["parent"] == parent].copy()
    if months:
        df = df[df["month"].isin(months)]
    if df.empty:
        return empty, None, None, ""

    # Prefer months from the requested window; fall back to any with spend
    month_list = sorted(df["month"].unique())
    if not month_list:
        return empty, None, None, ""
    m_cur = month_list[-1]
    # Prior = previous month key in window, else previous calendar month with spend
    m_prev = month_list[-2] if len(month_list) >= 2 else None
    if m_prev is None:
        # look at full sdf for a prior month with this parent
        all_m = sorted(sdf[sdf["parent"] == parent]["month"].unique())
        earlier = [m for m in all_m if m < m_cur]
        m_prev = earlier[-1] if earlier else None

    rows: list[dict] = []
    cur_incomplete = is_incomplete_budget_month(m_cur, today)
    for role, mk in (("Current", m_cur), ("Prior", m_prev)):
        if not mk:
            continue
        sub = (
            df[df["month"] == mk]
            .groupby("subcategory", as_index=False)["spend"]
            .sum()
        )
        # If prior month not in filtered df, pull from full sdf
        if sub.empty and role == "Prior" and sdf is not None:
            sub = (
                sdf[(sdf["parent"] == parent) & (sdf["month"] == mk)]
                .groupby("subcategory", as_index=False)["spend"]
                .sum()
            )
        for _, r in sub.iterrows():
            rows.append(
                {
                    "subcategory": r["subcategory"],
                    "month": mk,
                    "month_role": role,
                    "spend": float(r["spend"]),
                    "incomplete": bool(cur_incomplete and role == "Current"),
                }
            )

    out = pd.DataFrame(rows) if rows else empty
    cur_lab = month_key_short(m_cur) if m_cur else ""
    prev_lab = month_key_short(m_prev) if m_prev else None
    if m_prev and prev_lab and cur_lab:
        caption = f"Change: {cur_lab} vs {prev_lab}"
    else:
        caption = f"Change: {cur_lab}" if cur_lab else ""
    if cur_incomplete and m_cur:
        caption = (
            f"{caption} · {month_label_long(m_cur)} in progress (posted so far)"
            if caption
            else f"{month_label_long(m_cur)} in progress (posted so far)"
        )
    elif m_prev and prev_lab:
        # label incomplete months in window if any (rare)
        pass
    return out, m_cur, m_prev, caption


def _savings_outflow_by_month(actuals: Iterable[dict], daily: list[dict] | None = None) -> dict[str, float]:
    """Absolute Savings / Transfers outflows per month (allocated to savings)."""
    out: dict[str, float] = defaultdict(float)
    for a in actuals or []:
        amt = float(a.get("amount") or 0)
        if amt >= 0:
            continue
        cat = (a.get("category") or "").lower()
        parent = (a.get("parent") or "").lower()
        if "saving" in cat or "saving" in parent or cat == "savings":
            d = _parse_date(a.get("date"))
            if d:
                out[_month_key(d)] += abs(amt)
    if daily:
        for day in daily:
            d = _parse_date(day.get("date"))
            if not d:
                continue
            mk = _month_key(d)
            for f in day.get("flows") or []:
                amt = float(_flow_get(f, "amount") or 0)
                if amt >= 0:
                    continue
                cat = (_flow_get(f, "category") or "").lower()
                if "saving" in cat:
                    out[mk] += abs(amt)
    return dict(out)


GOAL_NARRATIVE = (
    "By 2028 the household is sustained on Alex's income. "
    "Jordan streams (primary $1,500 and side_gig secondary) should go to Savings when present — "
    "not cover living expenses."
)


def _bucket_beyond_plan(
    by_month: dict[str, float],
    savings: dict[str, float],
    *,
    plan_end_month: str,
    stream_label: str,
) -> tuple[list[str], list[dict], list[dict], float]:
    """Return beyond months, operating-dep rows, savings-ok rows, pct operating."""
    beyond = sorted(m for m in by_month if m > plan_end_month)
    operating_dep: list[dict] = []
    savings_ok: list[dict] = []
    for m in beyond:
        amt = by_month[m]
        sav = savings.get(m, 0.0)
        row = {
            "month": m,
            "amount": amt,
            "savings_out": sav,
            "stream": stream_label,
        }
        if amt > 0 and sav >= 0.8 * amt:
            savings_ok.append(row)
        elif amt > 0:
            operating_dep.append(row)
    n_beyond = len(beyond)
    n_op = len(operating_dep)
    pct = (100.0 * n_op / n_beyond) if n_beyond else 0.0
    return beyond, operating_dep, savings_ok, pct


def _level_from_pct(pct: float, n_beyond: int, *, orange_max_pct: float) -> tuple[str, str]:
    """pct = share of beyond-plan months left in operating (not saved)."""
    if n_beyond == 0 or pct <= 0:
        return "green", "on_plan"
    if pct > orange_max_pct:
        return "red", "dependent"
    return "orange", "watch"


def dependency_scorecard(
    idf: pd.DataFrame,
    *,
    actuals: Iterable[dict] | None = None,
    daily: list[dict] | None = None,
    side_gig_plan_end: date = SIDE_GIG_PLAN_END,
    secondary_primary_sunset: date = SECONDARY_SUNSET,
    orange_max_pct: float = 40.0,
) -> dict[str, Any]:
    """Income dependency scorecards for secondary + Jordan primary sunset.

    Streams:
      - Jordan secondary (side_gig ~$600) + other gifts: intended through side_gig_plan_end
        (default 2027-02). Beyond → flag if left in operating (not saved).
      - Jordan primary ($1,500/mo): OK through 2027 (sunset month); from 2028 operating
        reliance flags if still used for living expenses (Excel/twin: amount_by_year 2028=0).

    Threshold sketch (per lane, on beyond-plan months with that stream present):
      0% operating-dependent → green / on_plan
      0–40% → orange watch
      >40% → red dependent

    Overall level = worst of the lanes (red > orange > green).
    """
    side_gig_end_m = _month_key(side_gig_plan_end)
    primary_end_m = _month_key(secondary_primary_sunset)

    empty = {
        "side_gig_plan_end": side_gig_end_m,
        "secondary_primary_sunset": primary_end_m,
        "status": "no_data",
        "level": "neutral",
        "caption": "No income stream data yet.",
        "side_gig": {},
        "secondary_primary": {},
        "goal": GOAL_NARRATIVE,
        "orange_max_pct": orange_max_pct,
    }
    if idf is None or idf.empty:
        return empty

    savings = _savings_outflow_by_month(actuals or [], daily)

    def _sums(streams: set[str]) -> dict[str, float]:
        sub = idf[idf["stream"].isin(streams)]
        if sub.empty:
            return {}
        g = sub.groupby("month")["amount"].sum()
        return {str(k): float(v) for k, v in g.items()}

    # --- Side gig secondary only (Other/gifts are tertiary; not bound to Feb-2027 window) ---
    sec_by = _sums({STREAM_SIDE_GIG})
    sec_beyond, sec_op, sec_sav, sec_pct = _bucket_beyond_plan(
        sec_by, savings, plan_end_month=side_gig_end_m, stream_label="Jordan secondary"
    )
    sec_level, sec_status = _level_from_pct(sec_pct, len(sec_beyond), orange_max_pct=orange_max_pct)
    if len(sec_beyond) == 0:
        sec_caption = (
            f"Side gig/secondary stays within the intended window "
            f"(through {side_gig_end_m}). No beyond-plan operating use detected."
        )
    elif sec_status == "dependent":
        sec_caption = (
            f"Red dependent: {len(sec_op)}/{len(sec_beyond)} months after {side_gig_end_m} "
            f"({sec_pct:.0f}%) still use side_gig secondary for operating (not saved)."
        )
    else:
        sec_caption = (
            f"Orange watch: {len(sec_op)}/{len(sec_beyond)} months after {side_gig_end_m} "
            f"({sec_pct:.0f}%) leave side_gig secondary in operating cash."
        )

    # --- Jordan primary sunset (OK through 2027; flag 2028+) ---
    pri_by = _sums({STREAM_SECONDARY})
    pri_beyond, pri_op, pri_sav, pri_pct = _bucket_beyond_plan(
        pri_by, savings, plan_end_month=primary_end_m, stream_label="Jordan primary"
    )
    pri_level, pri_status = _level_from_pct(pri_pct, len(pri_beyond), orange_max_pct=orange_max_pct)
    if len(pri_beyond) == 0:
        pri_caption = (
            f"Jordan primary ($1,500) is within the sunset window "
            f"(OK through {primary_end_m}; Excel/twin 2028=$0). "
            f"No 2028+ operating reliance detected."
        )
    elif pri_status == "dependent":
        pri_caption = (
            f"Red dependent: {len(pri_op)}/{len(pri_beyond)} months in 2028+ "
            f"({pri_pct:.0f}%) still use Jordan primary for living expenses (not saved)."
        )
    else:
        pri_caption = (
            f"Orange watch: {len(pri_op)}/{len(pri_beyond)} months in 2028+ "
            f"({pri_pct:.0f}%) leave Jordan primary in operating cash."
        )

    rank = {"neutral": 0, "green": 1, "orange": 2, "red": 3}
    overall_level = max([sec_level, pri_level], key=lambda x: rank.get(x, 0))
    if overall_level == "green" and sec_status == "on_plan" and pri_status == "on_plan":
        overall_status = "on_plan"
    elif overall_level == "red":
        overall_status = "dependent"
    elif overall_level == "orange":
        overall_status = "watch"
    else:
        overall_status = "on_plan"

    caption_parts = [sec_caption, pri_caption]
    caption = " ".join(caption_parts)

    return {
        "side_gig_plan_end": side_gig_end_m,
        "secondary_primary_sunset": primary_end_m,
        "status": overall_status,
        "level": overall_level,
        "caption": caption,
        "side_gig": {
            "plan_end": side_gig_end_m,
            "level": sec_level,
            "status": sec_status,
            "caption": sec_caption,
            "beyond_plan_months": sec_beyond,
            "operating_dependent_months": sec_op,
            "savings_allocated_months": sec_sav,
            "in_plan_months": sorted(m for m in sec_by if m <= side_gig_end_m),
            "pct_operating_beyond": sec_pct,
        },
        "secondary_primary": {
            "sunset": primary_end_m,
            "level": pri_level,
            "status": pri_status,
            "caption": pri_caption,
            "beyond_plan_months": pri_beyond,
            "operating_dependent_months": pri_op,
            "savings_allocated_months": pri_sav,
            "in_plan_months": sorted(m for m in pri_by if m <= primary_end_m),
            "pct_operating_beyond": pri_pct,
        },
        "other_gifts": {
            "months_present": sorted(_sums({STREAM_OTHER}).keys()),
            "note": (
                "Other/gifts/discretionary are not on the side_gig clock; "
                "prefer routing large discretionary inflows to Savings when not needed for bills."
            ),
        },
        # Back-compat aliases (side_gig lane)
        "plan_end": side_gig_end_m,
        "beyond_plan_months": sec_beyond,
        "operating_dependent_months": sec_op,
        "savings_allocated_months": sec_sav,
        "pct_operating_beyond": sec_pct,
        "orange_max_pct": orange_max_pct,
        "goal": GOAL_NARRATIVE,
    }


def _resolve_parent_sub(a: dict) -> tuple[str, str]:
    """Prefer stored parent/subcategory; fall back to category→taxonomy map."""
    parent = (a.get("parent") or "").strip()
    sub = (a.get("subcategory") or "").strip()
    cat = (a.get("category") or "").strip()
    if parent and parent != "Uncategorized" and sub and sub != "Uncategorized":
        return parent, sub
    if parent and parent != "Uncategorized" and not sub:
        return parent, cat or "Uncategorized"
    # Missing / uncategorized parent → try excel/category taxonomy map
    if cat:
        try:
            from engine.bank_import import excel_to_parent_sub

            par, subcategory, _legacy = excel_to_parent_sub(cat)
            if par and par != "Uncategorized":
                return par, subcategory or cat or "Uncategorized"
            if subcategory:
                return parent or par or "Uncategorized", subcategory
        except Exception:
            pass
    return parent or "Uncategorized", sub or cat or "Uncategorized"


def spend_frame(actuals: Iterable[dict], *, source: str = "bank_csv") -> pd.DataFrame:
    """Debit actuals as spend by parent/sub/month (absolute).

    Uses bank_csv parent/subcategory when present; otherwise maps category
    through taxonomy v2 (`excel_name_to_new`).
    """
    rows = []
    for a in actuals:
        if source and a.get("source") != source:
            continue
        amt = float(a.get("amount") or 0)
        if amt >= 0:
            continue
        d = _parse_date(a.get("date"))
        if not d:
            continue
        parent, subcategory = _resolve_parent_sub(a)
        rows.append(
            {
                "date": d,
                "month": _month_key(d),
                "year": d.year,
                "spend": -amt,
                "parent": parent,
                "subcategory": subcategory,
                "label": a.get("label") or "",
                "category": a.get("category") or "",
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["date", "month", "year", "spend", "parent", "subcategory", "label", "category"]
        )
    return pd.DataFrame(rows)


def monthly_spend_by_parent(sdf: pd.DataFrame, months: list[str] | None = None) -> pd.DataFrame:
    if sdf is None or sdf.empty:
        return pd.DataFrame()
    df = sdf if not months else sdf[sdf["month"].isin(months)]
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(["month", "parent"], as_index=False)["spend"].sum()
    wide = g.pivot(index="month", columns="parent", values="spend").fillna(0.0)
    cols = [c for c in EXPENSE_PARENT_ORDER if c in wide.columns] + [
        c for c in wide.columns if c not in EXPENSE_PARENT_ORDER
    ]
    return wide[cols].sort_index()


def parent_averages_and_mom(
    sdf: pd.DataFrame, months: list[str] | None = None
) -> pd.DataFrame:
    """Per-parent average spend + MoM $ / % for last two months in window."""
    wide = monthly_spend_by_parent(sdf, months)
    if wide.empty:
        return pd.DataFrame()
    avg = wide.mean(axis=0)
    rows = []
    m_cur = wide.index[-1] if len(wide.index) else None
    m_prev = wide.index[-2] if len(wide.index) >= 2 else None
    for parent in wide.columns:
        cur = float(wide.loc[m_cur, parent]) if m_cur is not None else 0.0
        prev = float(wide.loc[m_prev, parent]) if m_prev is not None else None
        delta = None if prev is None else cur - prev
        if prev and prev != 0:
            pct = 100.0 * delta / prev
            pct_s = f"{pct:+.0f}%"
        elif cur == 0:
            pct_s = "—"
        else:
            pct_s = "new"
        rows.append(
            {
                "parent": parent,
                "avg": float(avg[parent]),
                "latest": cur,
                "latest_month": m_cur,
                "prior": prev,
                "prior_month": m_prev,
                "delta": delta,
                "delta_pct": pct_s,
            }
        )
    return pd.DataFrame(rows).sort_values("avg", ascending=False)


def seasonality_callouts(sdf: pd.DataFrame, *, min_months: int = 4) -> list[str]:
    """Simple highlights (e.g. utilities higher in certain months)."""
    if sdf is None or sdf.empty:
        return []
    callouts: list[str] = []
    months = sorted(sdf["month"].unique())
    if len(months) < min_months:
        return [
            f"Only {len(months)} month(s) of actuals — seasonality will firm up with more history."
        ]

    for parent in ("Utilities", "Dining", "Groceries", "Shopping", "School"):
        sub = sdf[sdf["parent"] == parent]
        if sub.empty:
            continue
        by_m = sub.groupby("month")["spend"].sum()
        if len(by_m) < min_months:
            continue
        mean = float(by_m.mean())
        if mean <= 0:
            continue
        peak_m = by_m.idxmax()
        peak_v = float(by_m.max())
        low_m = by_m.idxmin()
        low_v = float(by_m.min())
        if peak_v >= 1.25 * mean:
            callouts.append(
                f"**{parent}**: highest in {peak_m} (${peak_v:,.0f}) vs avg ${mean:,.0f}/mo "
                f"(low {low_m} ${low_v:,.0f})."
            )
    if not callouts:
        callouts.append("No strong seasonality spikes in the selected window (within ~25% of average).")
    return callouts[:6]


def latest_complete_month(sdf: pd.DataFrame, today: date | None = None) -> str | None:
    """Latest month in actuals that is not the in-progress calendar month (when possible)."""
    if sdf is None or sdf.empty:
        return None
    months = sorted(sdf["month"].unique())
    today = today or date.today()
    current = _month_key(today)
    complete = [m for m in months if m < current]
    if complete:
        return complete[-1]
    return months[-1] if months else None


def taxonomy_subs_for_parent(parent: str) -> list[str]:
    """Ordered subcategory names from taxonomy_v2 for a parent (empty if unknown)."""
    if not parent:
        return []
    try:
        from engine.bank_import import load_taxonomy

        tax = load_taxonomy()
        for p in tax.get("parents") or []:
            if (p.get("name") or "") == parent:
                return [c.get("name") for c in (p.get("children") or []) if c.get("name")]
    except Exception:
        pass
    return []


def subcategory_breakout(
    sdf: pd.DataFrame,
    parent: str,
    months: list[str] | None = None,
    *,
    include_zero_taxonomy: bool = False,
) -> pd.DataFrame:
    """Subcategory mix for one expense parent within an optional month window.

    Returns columns:
      subcategory | amount | pct_of_parent | latest | prior | delta | delta_pct | parent | parent_total

    Amounts are absolute spend ($) summed over the window. pct_of_parent is share of
    that parent bucket (0–100). MoM uses the last two months present in the window.
    """
    empty_cols = [
        "subcategory",
        "amount",
        "pct_of_parent",
        "latest",
        "prior",
        "delta",
        "delta_pct",
        "parent",
        "parent_total",
    ]
    if sdf is None or sdf.empty or not parent:
        return pd.DataFrame(columns=empty_cols)

    df = sdf[sdf["parent"] == parent].copy()
    if months:
        df = df[df["month"].isin(months)]
    if df.empty and not include_zero_taxonomy:
        return pd.DataFrame(columns=empty_cols)

    by_sub = (
        df.groupby("subcategory", as_index=False)["spend"].sum()
        if not df.empty
        else pd.DataFrame(columns=["subcategory", "spend"])
    )
    by_sub = by_sub.rename(columns={"spend": "amount"})

    tax_subs = taxonomy_subs_for_parent(parent)
    if include_zero_taxonomy and tax_subs:
        for s in tax_subs:
            if s not in set(by_sub["subcategory"]):
                by_sub = pd.concat(
                    [by_sub, pd.DataFrame([{"subcategory": s, "amount": 0.0}])],
                    ignore_index=True,
                )

    parent_total = float(by_sub["amount"].sum()) if not by_sub.empty else 0.0
    if parent_total > 0:
        by_sub["pct_of_parent"] = 100.0 * by_sub["amount"] / parent_total
    else:
        by_sub["pct_of_parent"] = 0.0

    # MoM from last two months in window (or in filtered df)
    month_list = sorted(df["month"].unique()) if not df.empty else []
    m_cur = month_list[-1] if month_list else None
    m_prev = month_list[-2] if len(month_list) >= 2 else None
    monthly = (
        df.groupby(["subcategory", "month"], as_index=False)["spend"].sum()
        if not df.empty
        else pd.DataFrame(columns=["subcategory", "month", "spend"])
    )
    latest_map: dict[str, float] = {}
    prior_map: dict[str, float] = {}
    if m_cur is not None and not monthly.empty:
        latest_map = {
            str(r["subcategory"]): float(r["spend"])
            for _, r in monthly[monthly["month"] == m_cur].iterrows()
        }
    if m_prev is not None and not monthly.empty:
        prior_map = {
            str(r["subcategory"]): float(r["spend"])
            for _, r in monthly[monthly["month"] == m_prev].iterrows()
        }

    rows = []
    for _, r in by_sub.iterrows():
        sub = str(r["subcategory"])
        cur = latest_map.get(sub, 0.0) if m_cur else None
        prev = prior_map.get(sub) if m_prev else None
        if prev is None and m_prev is None:
            delta = None
            pct_s = "—"
        else:
            prev_f = float(prev or 0.0)
            cur_f = float(cur or 0.0)
            delta = cur_f - prev_f
            if prev_f != 0:
                pct_s = f"{100.0 * delta / prev_f:+.0f}%"
            elif cur_f == 0:
                pct_s = "—"
            else:
                pct_s = "new"
        rows.append(
            {
                "subcategory": sub,
                "amount": float(r["amount"]),
                "pct_of_parent": float(r["pct_of_parent"]),
                "latest": cur if m_cur else None,
                "prior": prev if m_prev else None,
                "delta": delta,
                "delta_pct": pct_s,
                "parent": parent,
                "parent_total": parent_total,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=empty_cols)

    # Prefer taxonomy order, then remaining by amount desc
    if tax_subs:
        order_rank = {s: i for i, s in enumerate(tax_subs)}
        out["_ord"] = out["subcategory"].map(lambda s: order_rank.get(s, 10_000))
        out = out.sort_values(["_ord", "amount"], ascending=[True, False]).drop(columns=["_ord"])
    else:
        out = out.sort_values("amount", ascending=False)
    return out.reset_index(drop=True)



def monthly_spend_by_subcategory(
    sdf: pd.DataFrame,
    parent: str,
    months: list[str] | None = None,
    *,
    include_zero_taxonomy: bool = False,
) -> pd.DataFrame:
    """Wide month × subcategory spend for one parent (absolute $).

    Columns ordered by taxonomy when available, then remaining by total desc.
    Empty months in the requested window are filled with 0 when `months` is set.
    """
    if sdf is None or sdf.empty or not parent:
        return pd.DataFrame()
    df = sdf[sdf["parent"] == parent].copy()
    if months:
        df = df[df["month"].isin(months)]
    if df.empty and not (include_zero_taxonomy and taxonomy_subs_for_parent(parent)):
        return pd.DataFrame()

    if df.empty:
        wide = pd.DataFrame()
    else:
        g = df.groupby(["month", "subcategory"], as_index=False)["spend"].sum()
        wide = g.pivot(index="month", columns="subcategory", values="spend").fillna(0.0)

    tax_subs = taxonomy_subs_for_parent(parent)
    if include_zero_taxonomy and tax_subs:
        for s in tax_subs:
            if s not in wide.columns:
                wide[s] = 0.0

    if months:
        # Ensure every requested month appears (0-fill)
        for m in months:
            if m not in wide.index:
                wide.loc[m] = 0.0
        wide = wide.reindex(sorted(set(months) | set(wide.index))).loc[
            [m for m in months if m in wide.index]
        ]

    if wide.empty:
        return wide

    if tax_subs:
        ordered = [c for c in tax_subs if c in wide.columns]
        rest = sorted(
            [c for c in wide.columns if c not in ordered],
            key=lambda c: float(wide[c].sum()),
            reverse=True,
        )
        wide = wide[ordered + rest]
    else:
        totals = wide.sum(axis=0).sort_values(ascending=False)
        wide = wide[list(totals.index)]

    return wide.sort_index()


def subcategory_mom_matrix(
    sdf: pd.DataFrame,
    parent: str,
    months: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (dollar wide month×sub, pct-of-month-parent wide) for stacked MoM + table.

    pct cells are 0–100 share of that month's parent total (NaN when month total is 0).
    """
    wide = monthly_spend_by_subcategory(sdf, parent, months)
    if wide.empty:
        return wide, pd.DataFrame()
    month_tot = wide.sum(axis=1)
    pct = wide.div(month_tot.replace(0, pd.NA), axis=0) * 100.0
    return wide, pct


def parents_with_spend(sdf: pd.DataFrame, months: list[str] | None = None) -> list[str]:
    """Parents present in spend frame (featured order first, then rest by total)."""
    if sdf is None or sdf.empty:
        return []
    df = sdf if not months else sdf[sdf["month"].isin(months)]
    if df.empty:
        return []
    totals = df.groupby("parent")["spend"].sum().sort_values(ascending=False)
    featured = [p for p in FEATURED_EXPENSE_PARENTS if p in totals.index]
    ordered = [p for p in EXPENSE_PARENT_ORDER if p in totals.index and p not in featured]
    rest = [p for p in totals.index if p not in featured and p not in ordered]
    return featured + ordered + rest



# ---------------------------------------------------------------------------
# Budget vs actual (rules+planned pipeline vs bank_csv)
# ---------------------------------------------------------------------------

DEFAULT_MOM_VARIANCE_THRESHOLD = 500.0
DEFAULT_QOQ_VARIANCE_THRESHOLD = 1000.0
# Surface unplanned Chase spend (e.g. tutoring) even when parent rollup < MoM flag
UNBUDGETED_ADHOC_THRESHOLD = 200.0

MOM_THRESHOLD_RANGE = (500.0, 1000.0)
QOQ_THRESHOLD_RANGE = (1000.0, 5000.0)

# Soft cash allotments that do not reliably clear Chase as one payment —
# exclude their budget lines from budget_vs_actual / flux flags.
SOFT_BUDGET_CATEGORIES = frozenset()  # Wife's allowance stays in flux (Alex: miss target = useful flag)
SOFT_BUDGET_PARENTS = frozenset()

# Revolving card paydowns (settlement of prior spend) — not compared to Student Loans plan.
CARD_PAYMENT_CATEGORIES = frozenset(
    {
        "Meriott Chase",
        "Marriott Chase",
    }
)
CARD_PAYMENT_SUBCATEGORIES = frozenset(
    {
        "Marriott Chase",
    }
)

SAVINGS_FLUX_PARENT = "Transfers / Savings"

BUDGET_LIMITATIONS_NOTE = (
    "Budget proxy = recurring Data Input rules projected into the calendar month "
    "+ planned overlays (Budget workbook / Excel parity). "
    "For months before the twin start (or before a rule's start_date), amounts are "
    "approximate: current rule amounts (amount_by_year when set) applied to that "
    "calendar month. Planned items override the same category in that month, except "
    "Home Mortgage where distinct scheduled amounts (1st + 2nd) are merged. "
    "In the current (incomplete) calendar month, only budget lines due before "
    "as_of are scored (same-day and future dues are pending); underspend is not flagged. "
    "Actuals = bank_csv debits. Income / inflows are excluded from expense variance. "
    "Extra mortgage principal counts toward the Savings plan, not as Housing overspend. "
    "Wife's allowance stays in flux so missing the allotment flags. "
    "Chase card payments excluded from flux (settlement, not a bill-budget line). "
    "Transfers/Savings flags only when under plan (over-saving is OK)."
)


def _norm_cat_key(cat: str | None) -> str:
    return (cat or "").strip().lower().replace("'", "").replace(" ", "")


def is_soft_budget_category(category: str | None) -> bool:
    """True only for categories listed in SOFT_BUDGET_CATEGORIES (currently none)."""
    return (category or "").strip() in SOFT_BUDGET_CATEGORIES


def is_card_payment_row(category: str | None = None, subcategory: str | None = None) -> bool:
    """True for revolving Chase/Marriott card paydowns (not Student Loans)."""
    cat = (category or "").strip()
    sub = (subcategory or "").strip()
    if cat in CARD_PAYMENT_CATEGORIES or sub in CARD_PAYMENT_SUBCATEGORIES:
        return True
    # Typo-tolerant Meriott / Marriott Chase
    low = f"{cat} {sub}".lower()
    if "meriott chase" in low or "marriott chase" in low:
        return True
    return False


def is_incomplete_budget_month(month: str, as_of: date | None = None) -> bool:
    """True when ``month`` is the calendar month of ``as_of`` (still in progress)."""
    if not month:
        return False
    as_of = as_of or date.today()
    return month == _month_key(as_of)


def partial_month_flux_note(month: str, as_of: date | None = None) -> str:
    """Caption when scoring an in-progress calendar month."""
    if not is_incomplete_budget_month(month, as_of):
        return ""
    as_of = as_of or date.today()
    label = month_label_long(month)
    return (
        f"{label} is in progress — only bills due before "
        f"{as_of.isoformat()} are scored."
    )


def filter_budget_due_through(
    bdf: "pd.DataFrame | None",
    month: str,
    as_of: date | None = None,
) -> "pd.DataFrame":
    """For the current calendar month, drop budget lines with date >= as_of.

    Same-day dues are pending (ACH often posts later the same day). Complete
    months are unchanged. Rows without a parseable date are kept.
    """
    if bdf is None or bdf.empty or not month:
        return bdf if bdf is not None else pd.DataFrame()
    as_of = as_of or date.today()
    bud = bdf[bdf["month"] == month].copy()
    if bud.empty or not is_incomplete_budget_month(month, as_of):
        return bud
    if "date" not in bud.columns:
        return bud

    def _due(row) -> bool:
        d = _parse_date(row.get("date"))
        if d is None:
            return True
        return d < as_of

    return bud[bud.apply(_due, axis=1)].copy()


def apply_flux_flags(out: "pd.DataFrame", threshold: float) -> "pd.DataFrame":
    """Set delta / abs_delta / flagged. Savings parent: undersave-only."""
    if out is None or out.empty:
        return out
    out = out.copy()
    thr = float(threshold)
    out["delta"] = out["actual"] - out["budgeted"]
    out["abs_delta"] = out["delta"].abs()
    flagged = out["abs_delta"] >= thr
    if "parent" in out.columns:
        sav = out["parent"] == SAVINGS_FLUX_PARENT
        # Over-saving (positive delta) never flags; under-plan only when delta <= -thr
        flagged = (~sav & flagged) | (sav & (out["delta"] <= -thr))
    out["flagged"] = flagged
    return out


def flux_exclusion_notes(
    sdf: "pd.DataFrame | None",
    bdf: "pd.DataFrame | None",
    month: str,
) -> list[str]:
    """Human notes when soft-allowance / card-payment exclusions apply for month."""
    notes: list[str] = []
    if bdf is not None and not bdf.empty and month:
        bud = bdf[bdf["month"] == month]
        if not bud.empty and bud["category"].map(is_soft_budget_category).any():
            notes.append(
                "Wife's allowance compared to Chase (Jordan Zelle, etc.); cleaner/tutor remapped out of Allowance."
            )
    if sdf is not None and not sdf.empty and month:
        act = sdf[sdf["month"] == month]
        if not act.empty:
            hit = act.apply(
                lambda r: is_card_payment_row(r.get("category"), r.get("subcategory")),
                axis=1,
            )
            if bool(hit.any()):
                notes.append(
                    "Chase card payments excluded from flux (settlement, not a bill-budget line)."
                )
    return notes


def _month_bounds(month_key: str) -> tuple[date, date]:
    """Inclusive start/end dates for YYYY-MM."""
    y, m = int(month_key[:4]), int(month_key[5:7])
    from calendar import monthrange

    return date(y, m, 1), date(y, m, monthrange(y, m)[1])


def trailing_month_keys(month_key: str, n: int = 3) -> list[str]:
    """Last n calendar months ending at month_key (inclusive), oldest→newest."""
    y, m = int(month_key[:4]), int(month_key[5:7])
    out: list[str] = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    return list(reversed(out))


def _flow_parent_sub(category: str | None, label: str | None = "") -> tuple[str, str]:
    cat = (category or "").strip() or "Uncategorized"
    try:
        from engine.bank_import import excel_to_parent_sub

        par, sub, _legacy = excel_to_parent_sub(cat)
        if par and par != "Uncategorized":
            return par, sub or cat
        if sub:
            return par or "Uncategorized", sub
    except Exception:
        pass
    return "Uncategorized", cat


def _rule_window(rule: dict) -> tuple[date | None, date | None]:
    r_start = _parse_date(rule.get("start_date")) if rule.get("start_date") else None
    r_end = _parse_date(rule.get("end_date")) if rule.get("end_date") else None
    return r_start, r_end


def _rule_covers_month(rule: dict, month_key: str) -> bool:
    start_b, end_b = _month_bounds(month_key)
    r_start, r_end = _rule_window(rule)
    if r_end is not None and r_end < start_b:
        return False
    if r_start is not None and r_start > end_b:
        return False
    return True


def _rule_dedupe_key(rule: dict) -> tuple:
    """One budget stamp per category (+ cadence family).

    Collapses Excel/year variants that share a category even when DOM differs
    (e.g. Wife's allowance day-27 vs day-28 versions).

    Home Mortgage is handled separately in ``_select_rules_for_month`` so
    1st + 2nd mortgages (same category, different amounts) are both kept.
    """
    cadence = (rule.get("cadence") or "monthly_dom").lower()
    cat = rule.get("category") or ""
    family = "biweekly" if cadence == "biweekly" else "monthly"
    return (cat, family)


def _is_mortgage_mortgage_rule(rule: dict) -> bool:
    cat = (rule.get("category") or "").lower()
    lab = (rule.get("label") or "").lower()
    return "mortgage" in cat or "home mortgage" in lab or "homeloan" in cat or "homeloan" in lab


def _rocket_amount_key(rule: dict) -> float:
    return round(abs(float(rule.get("amount") or 0)), 2)


def _select_rocket_rules_for_month(
    rocket_rules: list[dict],
    month_key: str,
    *,
    approximate: bool,
) -> list[dict]:
    """Keep all distinct scheduled Home Mortgage amounts for the month.

    1st (~2450) and 2nd (~950) share category ``Home Mortgage`` but must both
    count in Housing budget. Later-era single payments (e.g. 2028+) stay out of
    earlier approximate stamps by cohorting on the nearest window start/end.
    """
    if not rocket_rules:
        return []

    start_b, end_b = _month_bounds(month_key)
    covering = [r for r in rocket_rules if _rule_covers_month(r, month_key)]

    def _pick_per_amount(group: list[dict]) -> list[dict]:
        by_amt: dict[float, dict] = {}
        for r in group:
            amt = _rocket_amount_key(r)
            prev = by_amt.get(amt)
            if prev is None:
                by_amt[amt] = r
                continue

            def _score(rule: dict) -> tuple:
                rs, _re = _rule_window(rule)
                lab = (rule.get("label") or "").lower()
                excelish = 1 if "excel" in lab else 0
                start_ord = rs.toordinal() if rs else 0
                return (excelish, -start_ord)

            if _score(r) < _score(prev):
                by_amt[amt] = r
        return list(by_amt.values())

    if covering:
        return _pick_per_amount(covering)
    if not approximate:
        return []

    future: list[dict] = []
    past: list[dict] = []
    for r in rocket_rules:
        rs, re = _rule_window(r)
        if rs is not None and rs > end_b:
            future.append(r)
        elif re is not None and re < start_b:
            past.append(r)
        else:
            future.append(r)

    cohort: list[dict] = []
    if future:
        future.sort(key=lambda r: (_rule_window(r)[0] or date.max))
        nearest_start = _rule_window(future[0])[0]
        cohort = [r for r in future if _rule_window(r)[0] == nearest_start]
    elif past:
        past.sort(
            key=lambda r: -((_rule_window(r)[1] or date.min).toordinal())
        )
        nearest_end = _rule_window(past[0])[1]
        cohort = [r for r in past if _rule_window(r)[1] == nearest_end]
    return _pick_per_amount(cohort)


def _select_rules_for_month(
    rules: Iterable[dict],
    month_key: str,
    *,
    approximate: bool,
) -> list[dict]:
    """Pick at most one enabled expense rule per category/cadence key for month.

    Strict: only rules whose start/end cover the month.
    Approximate: if none cover, use the nearest future window (else nearest past)
    so pre-twin months get a single Data Input stamp — never stack year variants.

    Exception: Home Mortgage keeps every distinct scheduled amount in the
    active window (1st + 2nd mortgage).
    """
    start_b, end_b = _month_bounds(month_key)
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    rocket_rules: list[dict] = []
    for rule in rules or []:
        if not rule.get("enabled", True):
            continue
        if _is_mortgage_mortgage_rule(rule):
            rocket_rules.append(rule)
            continue
        # Skip pure income rules early (amount may be year-dependent; still allow expand filter)
        by_key[_rule_dedupe_key(rule)].append(rule)

    selected: list[dict] = list(
        _select_rocket_rules_for_month(
            rocket_rules, month_key, approximate=approximate
        )
    )
    for _key, group in by_key.items():
        covering = [r for r in group if _rule_covers_month(r, month_key)]
        def _prefer_base(r: dict) -> tuple:
            """Prefer Data Input base over Excel-stamped duplicates when tied."""
            rs, _re = _rule_window(r)
            start_ord = rs.toordinal() if rs else 0
            lab = (r.get("label") or "").lower()
            excelish = 1 if "excel" in lab else 0
            # among non-excel, prefer smaller |amount| (base DOM); among excel, larger ok
            return (excelish, abs(float(r.get("amount") or 0)), -start_ord)

        if covering:
            # Overlap quirk: prefer non-Excel / base amount, then later start
            covering.sort(key=_prefer_base)
            selected.append(covering[0])
            continue
        if not approximate:
            continue
        # Nearest window: prefer earliest start_date on/after month, else latest ending before month
        future = []
        past = []
        for r in group:
            rs, re = _rule_window(r)
            if rs is not None and rs > end_b:
                future.append(r)
            elif re is not None and re < start_b:
                past.append(r)
            else:
                future.append(r)
        pick = None
        if future:
            future.sort(key=lambda r: ((_rule_window(r)[0] or date.max), _prefer_base(r)))
            pick = future[0]
        elif past:
            past.sort(
                key=lambda r: (
                    -((_rule_window(r)[1] or date.min).toordinal()),
                    _prefer_base(r),
                )
            )
            pick = past[0]
        if pick is not None:
            selected.append(pick)
    return selected


def _expand_rule_expense_in_month(rule: dict, month_key: str) -> list[dict]:
    """Expense (negative) occurrences of one rule inside month_key."""
    from engine.project import _year_amount, _biweekly_dates, _dom_in_month, _parse_date as pparse

    start_b, end_b = _month_bounds(month_key)
    cadence = (rule.get("cadence") or "monthly_dom").lower()
    category = rule.get("category") or "Uncategorized"
    label = rule.get("label") or category
    rows: list[dict] = []

    if cadence == "biweekly":
        anchor_raw = rule.get("anchor_date") or "2026-09-11"
        try:
            anchor = pparse(anchor_raw) if not isinstance(anchor_raw, date) else anchor_raw
        except Exception:
            anchor = date(2026, 9, 11)
        if isinstance(anchor, datetime):
            anchor = anchor.date()
        for d in _biweekly_dates(anchor, start_b, end_b, int(rule.get("interval_days") or 14)):
            amt = float(_year_amount(rule, d.year))
            if amt >= 0:
                continue
            parent, sub = _flow_parent_sub(category, label)
            rows.append(
                {
                    "date": d,
                    "month": month_key,
                    "budget": -amt,
                    "parent": parent,
                    "subcategory": sub,
                    "category": category,
                    "label": label,
                    "source": "rule",
                }
            )
    else:
        dom = int(rule.get("day_of_month") or 1)
        d = _dom_in_month(start_b.year, start_b.month, dom)
        if d is None or not (start_b <= d <= end_b):
            return rows
        amt = float(_year_amount(rule, d.year))
        if amt >= 0:
            return rows
        parent, sub = _flow_parent_sub(category, label)
        rows.append(
            {
                "date": d,
                "month": month_key,
                "budget": -amt,
                "parent": parent,
                "subcategory": sub,
                "category": category,
                "label": label,
                "source": "rule",
            }
        )
    return rows


def budget_spend_frame(
    rules: Iterable[dict],
    planned: Iterable[dict] | None,
    months: list[str],
    *,
    approximate_pre_start: bool = True,
    twin_start: date | None = None,
) -> pd.DataFrame:
    """Expense budget proxy by month/parent/sub from rules + planned.

    Planned items in a month override rule totals for the same *category*
    (Budget workbook / Excel overlays replace the recurring stamp), except
    Home Mortgage: distinct scheduled amounts are merged so a planned 1st
    (~2450) does not drop the 2nd mortgage rule (~950).

    When ``approximate_pre_start`` is True (default), months before a rule's
    start_date (or before twin start) still get a single nearest Data Input
    stamp per category — never stacked year-variants. Document in the UI.
    """
    empty = pd.DataFrame(
        columns=[
            "date",
            "month",
            "budget",
            "parent",
            "subcategory",
            "category",
            "label",
            "source",
        ]
    )
    if not months:
        return empty

    _ = twin_start  # caller/docs hook
    rule_rows: list[dict] = []
    for mk in months:
        chosen = _select_rules_for_month(rules, mk, approximate=approximate_pre_start)
        for rule in chosen:
            rule_rows.extend(_expand_rule_expense_in_month(rule, mk))

    planned_rows: list[dict] = []
    for it in planned or []:
        if it.get("enabled", True) is False:
            continue
        d = _parse_date(it.get("date"))
        if not d:
            continue
        mk = _month_key(d)
        if mk not in months:
            continue
        amt = float(it.get("amount") or 0)
        if amt >= 0:
            continue
        cat = it.get("category") or "Planned"
        label = it.get("label") or cat
        parent, sub = _flow_parent_sub(cat, label)
        planned_rows.append(
            {
                "date": d,
                "month": mk,
                "budget": -amt,
                "parent": parent,
                "subcategory": sub,
                "category": cat,
                "label": label,
                "source": "planned",
            }
        )

    if not rule_rows and not planned_rows:
        return empty

    planned_cats = {(r["month"], r["category"]) for r in planned_rows}
    planned_rocket_amts = {
        (r["month"], round(float(r["budget"]), 2))
        for r in planned_rows
        if "rocket" in str(r.get("category") or "").lower()
        or "rocket" in str(r.get("subcategory") or "").lower()
        or "rocket" in str(r.get("label") or "").lower()
    }
    kept_rules: list[dict] = []
    for r in rule_rows:
        key = (r["month"], r["category"])
        if key not in planned_cats:
            kept_rules.append(r)
            continue
        # Planned overrides same category — but never collapse a distinct mortgage amount
        is_mortgage = (
            "rocket" in str(r.get("category") or "").lower()
            or "rocket" in str(r.get("subcategory") or "").lower()
            or "rocket" in str(r.get("label") or "").lower()
        )
        if is_mortgage:
            amt_key = (r["month"], round(float(r["budget"]), 2))
            if amt_key not in planned_rocket_amts:
                kept_rules.append(r)
    all_rows = kept_rules + planned_rows
    if not all_rows:
        return empty
    return pd.DataFrame(all_rows)


def monthly_budget_by_parent(bdf: pd.DataFrame, months: list[str] | None = None) -> pd.DataFrame:
    if bdf is None or bdf.empty:
        return pd.DataFrame()
    df = bdf if not months else bdf[bdf["month"].isin(months)]
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(["month", "parent"], as_index=False)["budget"].sum()
    wide = g.pivot(index="month", columns="parent", values="budget").fillna(0.0)
    cols = [c for c in EXPENSE_PARENT_ORDER if c in wide.columns] + [
        c for c in wide.columns if c not in EXPENSE_PARENT_ORDER
    ]
    return wide[cols].sort_index()


def mortgage_extra_savings_credit(
    sdf: pd.DataFrame | None,
    bdf: pd.DataFrame | None,
    month: str,
) -> dict[str, Any]:
    """How much extra mortgage principal should count toward the Savings plan.

    Demo model: scheduled mortgage (1st+2nd) is Housing; anything above that
    up to the Savings budget is the monthly debt-payoff quota, not Housing
    overspend and not a Savings miss.
    """
    scheduled = 0.0
    if bdf is not None and not bdf.empty:
        bud = bdf[bdf["month"] == month]
        if not bud.empty:
            mask = bud["category"].astype(str).str.lower().str.contains("rocket") | bud[
                "subcategory"
            ].astype(str).str.lower().str.contains("rocket")
            scheduled = float(bud.loc[mask, "budget"].sum())

    actual_mortgage = 0.0
    if sdf is not None and not sdf.empty:
        act = sdf[sdf["month"] == month]
        if not act.empty:
            mask = act["category"].astype(str).str.lower().str.contains("rocket") | act[
                "subcategory"
            ].astype(str).str.lower().str.contains("rocket")
            actual_mortgage = float(act.loc[mask, "spend"].sum())

    extra = max(0.0, actual_mortgage - scheduled)

    savings_budget = 0.0
    if bdf is not None and not bdf.empty:
        bud = bdf[(bdf["month"] == month) & (bdf["parent"] == "Transfers / Savings")]
        if not bud.empty:
            savings_budget = float(bud["budget"].sum())

    savings_actual_raw = 0.0
    if sdf is not None and not sdf.empty:
        act = sdf[(sdf["month"] == month) & (sdf["parent"] == "Transfers / Savings")]
        if not act.empty:
            savings_actual_raw = float(act["spend"].sum())

    applied = min(extra, max(0.0, savings_budget)) if savings_budget > 0 else 0.0
    note = ""
    if applied > 0.005:
        note = (
            f"Counted ${applied:,.2f} extra mortgage principal as Savings "
            f"(debt payoff), not Housing overspend."
        )
    return {
        "scheduled_rocket": scheduled,
        "actual_mortgage": actual_mortgage,
        "extra_to_mortgage": extra,
        "savings_budget": savings_budget,
        "savings_actual_raw": savings_actual_raw,
        "applied": applied,
        "note": note,
    }


def mortgage_extra_on_target(meta: dict[str, Any] | None) -> bool:
    """True when Savings quota is met via mortgage extra credit (not an undersave)."""
    if not meta:
        return False
    applied = float(meta.get("applied") or 0.0)
    if applied <= 0.005:
        return False
    budget = float(meta.get("savings_budget") or 0.0)
    raw = float(meta.get("savings_actual_raw") or 0.0)
    return (raw + applied) + 0.005 >= budget


def savings_flux_status_message(meta: dict[str, Any] | None) -> str:
    """Plain-English Savings status when mortgage-extra credit applies."""
    if not meta or float(meta.get("applied") or 0) <= 0.005:
        return ""
    budget = float(meta.get("savings_budget") or 0.0)
    applied = float(meta.get("applied") or 0.0)
    raw = float(meta.get("savings_actual_raw") or 0.0)
    extra_sav = max(0.0, raw)  # SAV account transfers beyond the Mortgage credit
    if not mortgage_extra_on_target(meta):
        short = max(0.0, budget - (raw + applied))
        return (
            f"Savings quota ${budget:,.0f} not fully met "
            f"(${applied:,.0f} extra mortgage + ${raw:,.0f} to SAV accounts; "
            f"short ${short:,.0f})."
        )
    if extra_sav > 0.5:
        return (
            f"Savings quota ${budget:,.0f} met (including ${applied:,.0f} extra paid to Mortgage). "
            f"Extra ${extra_sav:,.0f} to savings accounts — ahead of plan, not a miss."
        )
    return (
        f"Savings quota ${budget:,.0f} met (including ${applied:,.0f} extra paid to Mortgage). "
        "On target."
    )


def mortgage_extra_drove_bullets(
    parent: str,
    meta: dict[str, Any] | None,
) -> list[str]:
    """Short plain-English bullets for Housing / Transfers-Savings expanders."""
    if not meta or float(meta.get("applied") or 0) <= 0.005:
        return []
    scheduled = float(meta.get("scheduled_rocket") or 0.0)
    applied = float(meta.get("applied") or 0.0)
    budget = float(meta.get("savings_budget") or 0.0)
    raw = float(meta.get("savings_actual_raw") or 0.0)
    p = (parent or "").strip()
    if p == "Transfers / Savings":
        bullets = [
            f"Plan: ${budget:,.0f} debt-payoff / savings quota",
            f"Counted toward quota: ${applied:,.0f} extra mortgage principal",
        ]
        if raw > 0.5:
            bullets.append(f"Also transferred to SAV accounts: ${raw:,.0f}")
        if mortgage_extra_on_target(meta):
            bullets.append("Result: quota met")
        else:
            short = max(0.0, budget - (raw + applied))
            bullets.append(f"Result: still short ${short:,.0f} vs plan")
        return bullets
    if p == "Housing":
        return [
            f"Scheduled mortgage (1st+2nd): ${scheduled:,.0f}",
            f"Extra principal ${applied:,.0f} counted as Savings (not Housing overspend)",
            "Housing vs plan: on target",
        ]
    return []


def reallocate_mortgage_extra_to_savings(
    out: pd.DataFrame,
    sdf: pd.DataFrame | None,
    bdf: pd.DataFrame | None,
    month: str,
    *,
    level: str = "parent",
    parent: str | None = None,
    mom_threshold: float = DEFAULT_MOM_VARIANCE_THRESHOLD,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Move excess Mortgage principal from Housing actual into Savings actual.

    Insights / variance only — does not change cash-engine balances.
    """
    meta = mortgage_extra_savings_credit(sdf, bdf, month)
    applied = float(meta.get("applied") or 0.0)
    if out is None or out.empty or applied <= 0.005:
        return out, meta

    out = out.copy()
    if level == "subcategory":
        # Housing drill: reduce Home Mortgage subcategory actual
        if "subcategory" in out.columns and (
            parent in (None, "All parents", "Housing") or parent == "Housing"
        ):
            rmask = out["subcategory"].astype(str).str.contains(
                "Mortgage", case=False, na=False
            )
            if rmask.any():
                idx = out.index[rmask][0]
                out.loc[idx, "actual"] = float(out.loc[idx, "actual"]) - applied
        # Savings drill: credit Savings subcategory
        if "subcategory" in out.columns and (
            parent in (None, "All parents", "Transfers / Savings")
        ):
            smask = out["subcategory"].astype(str) == "Savings"
            if smask.any():
                out.loc[smask, "actual"] = out.loc[smask, "actual"] + applied
            elif parent == "Transfers / Savings":
                out = pd.concat(
                    [
                        out,
                        pd.DataFrame(
                            [
                                {
                                    "parent": "Transfers / Savings",
                                    "subcategory": "Savings",
                                    "budgeted": float(meta["savings_budget"]),
                                    "actual": float(meta["savings_actual_raw"])
                                    + applied,
                                    "month": month,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
    else:
        hmask = out["parent"] == "Housing"
        if hmask.any():
            out.loc[hmask, "actual"] = out.loc[hmask, "actual"] - applied
        smask = out["parent"] == "Transfers / Savings"
        if smask.any():
            out.loc[smask, "actual"] = out.loc[smask, "actual"] + applied
        elif float(meta.get("savings_budget") or 0) > 0 or float(
            meta.get("savings_actual_raw") or 0
        ) > 0:
            out = pd.concat(
                [
                    out,
                    pd.DataFrame(
                        [
                            {
                                "parent": "Transfers / Savings",
                                "budgeted": float(meta["savings_budget"]),
                                "actual": float(meta["savings_actual_raw"]) + applied,
                                "month": month,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )

    out = apply_flux_flags(out, mom_threshold)
    if "month" not in out.columns:
        out["month"] = month
    else:
        out["month"] = out["month"].fillna(month)
    return out, meta


def budget_vs_actual_table(
    sdf: pd.DataFrame,
    bdf: pd.DataFrame,
    month: str,
    *,
    parent: str | None = None,
    level: str = "parent",
    mom_threshold: float = DEFAULT_MOM_VARIANCE_THRESHOLD,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Budgeted vs actual vs delta for one month.

    level='parent' → one row per parent
    level='subcategory' → rows for parent (required) broken by subcategory

    Columns: parent, subcategory?, budgeted, actual, delta, abs_delta, flagged
    delta = actual - budgeted (positive = overspent vs plan)

    Extra mortgage principal (above scheduled 1st+2nd) is reallocated toward
    Transfers/Savings actual for variance — see ``reallocate_mortgage_extra_to_savings``.
    Meta is attached on ``DataFrame.attrs['mortgage_extra_savings']``.

    When ``month`` is the current calendar month of ``as_of`` (default today),
    budget lines with ``date >= as_of`` are excluded (pending — same-day ACH
    may not have cleared). Underspend on an incomplete month is not flagged.
    """
    cols = ["parent", "budgeted", "actual", "delta", "abs_delta", "flagged", "month"]
    if level == "subcategory":
        cols = ["parent", "subcategory", "budgeted", "actual", "delta", "abs_delta", "flagged", "month"]

    if not month:
        return pd.DataFrame(columns=cols)

    as_of = as_of or date.today()
    incomplete = is_incomplete_budget_month(month, as_of)

    act = sdf[sdf["month"] == month] if sdf is not None and not sdf.empty else pd.DataFrame()
    # Score only budget due on/before as_of when the month is still in progress
    if incomplete:
        bud = filter_budget_due_through(bdf, month, as_of)
    else:
        bud = bdf[bdf["month"] == month] if bdf is not None and not bdf.empty else pd.DataFrame()

    # Soft-budget exclusions (none currently — Wife's allowance included in flux per Alex).
    if not bud.empty and "category" in bud.columns:
        bud = bud[~bud["category"].map(is_soft_budget_category)].copy()
    # Revolving card paydowns are settlement, not the Student Loans bill-budget line.
    if not act.empty:
        card_mask = act.apply(
            lambda r: is_card_payment_row(r.get("category"), r.get("subcategory")),
            axis=1,
        )
        act = act[~card_mask].copy()

    if parent and parent != "All parents":
        if not act.empty:
            act = act[act["parent"] == parent]
        if not bud.empty:
            bud = bud[bud["parent"] == parent]

    if level == "subcategory":
        key = ["parent", "subcategory"]
        a = (
            act.groupby(key, as_index=False)["spend"].sum().rename(columns={"spend": "actual"})
            if not act.empty
            else pd.DataFrame(columns=key + ["actual"])
        )
        b = (
            bud.groupby(key, as_index=False)["budget"].sum().rename(columns={"budget": "budgeted"})
            if not bud.empty
            else pd.DataFrame(columns=key + ["budgeted"])
        )
        out = pd.merge(b, a, on=key, how="outer").fillna(0.0)
    else:
        a = (
            act.groupby("parent", as_index=False)["spend"].sum().rename(columns={"spend": "actual"})
            if not act.empty
            else pd.DataFrame(columns=["parent", "actual"])
        )
        b = (
            bud.groupby("parent", as_index=False)["budget"].sum().rename(columns={"budget": "budgeted"})
            if not bud.empty
            else pd.DataFrame(columns=["parent", "budgeted"])
        )
        out = pd.merge(b, a, on="parent", how="outer").fillna(0.0)

    if out.empty:
        empty = pd.DataFrame(columns=cols)
        empty.attrs["mortgage_extra_savings"] = mortgage_extra_savings_credit(sdf, bdf, month)
        return empty

    out = apply_flux_flags(out, mom_threshold)
    out["month"] = month

    # Reallocate using month budget after due-through filter so scheduled Mortgage
    # / Savings plan match what is scored for incomplete months. Pass full sdf
    # (parent filter is reapplied inside table build only).
    bdf_for_credit = bdf
    if incomplete and bdf is not None and not bdf.empty:
        # Replace this month's rows with due-through subset; keep other months intact
        other = bdf[bdf["month"] != month]
        due = filter_budget_due_through(bdf, month, as_of)
        bdf_for_credit = pd.concat([other, due], ignore_index=True) if not due.empty or not other.empty else due
    out, meta = reallocate_mortgage_extra_to_savings(
        out,
        sdf,
        bdf_for_credit,
        month,
        level=level,
        parent=parent,
        mom_threshold=mom_threshold,
    )

    # Prefer taxonomy parent order
    if "parent" in out.columns:
        rank = {p: i for i, p in enumerate(EXPENSE_PARENT_ORDER)}
        out["_ord"] = out["parent"].map(lambda p: rank.get(p, 10_000))
        sort_cols = ["_ord", "abs_delta"]
        out = out.sort_values(sort_cols, ascending=[True, False]).drop(columns=["_ord"])

    out = out.reset_index(drop=True)
    # Incomplete month: underspend flags are premature (ACH / DOM not reached yet).
    if incomplete and not out.empty and "flagged" in out.columns and "delta" in out.columns:
        under = out["delta"] < 0
        out.loc[under, "flagged"] = False
    out.attrs["mortgage_extra_savings"] = meta
    out.attrs["as_of"] = as_of
    out.attrs["incomplete_month"] = incomplete
    out.attrs["partial_month_note"] = partial_month_flux_note(month, as_of)
    return out



def unbudgeted_adhoc_flags(
    sdf,
    bdf,
    month: str,
    *,
    threshold: float = UNBUDGETED_ADHOC_THRESHOLD,
) -> list[dict]:
    """Subcategories with ~$0 plan but meaningful Chase spend (ad hoc / unforecasted).

    Does not create recurring forecasts — only highlights actuals for flux honesty
    (e.g. tutoring). Skips card-payment rows.
    """
    import pandas as pd

    if sdf is None or sdf.empty:
        return []
    thr = float(threshold)
    act = sdf[sdf["month"] == month].copy()
    if act.empty:
        return []
    if "category" in act.columns:
        act = act[~act["category"].map(lambda c: is_card_payment_row(c, None))].copy()
    # budget by parent/subcategory
    bud_map: dict[tuple[str, str], float] = {}
    if bdf is not None and not bdf.empty:
        b = bdf[bdf["month"] == month]
        bcol = "budget" if "budget" in b.columns else ("amount" if "amount" in b.columns else None)
        if bcol and "parent" in b.columns:
            subcol = "subcategory" if "subcategory" in b.columns else None
            for _, r in b.iterrows():
                key = (str(r.get("parent") or ""), str(r.get(subcol) or r.get("category") or ""))
                bud_map[key] = bud_map.get(key, 0.0) + abs(float(r.get(bcol) or 0))
                # also parent+category key
                key2 = (str(r.get("parent") or ""), str(r.get("category") or ""))
                bud_map[key2] = bud_map.get(key2, 0.0) + abs(float(r.get(bcol) or 0))

    g = act.groupby(["parent", "subcategory"], dropna=False)["spend"].sum().reset_index()
    out = []
    for _, r in g.iterrows():
        parent = str(r["parent"] or "")
        sub = str(r["subcategory"] or "")
        spent = float(r["spend"] or 0)
        if spent < thr:
            continue
        planned = float(bud_map.get((parent, sub), 0.0))
        if planned >= thr:  # has a real plan line
            continue
        out.append(
            {
                "parent": parent,
                "subcategory": sub,
                "budgeted": planned,
                "actual": spent,
                "delta": spent - planned,
                "abs_delta": abs(spent - planned),
                "month": month,
                "kind": "unbudgeted_adhoc",
                "summary": f"{sub or parent}: ${spent:,.0f} spent with no plan line (ad hoc)",
            }
        )
    out.sort(key=lambda x: -x["abs_delta"])
    return out


def variance_scorecard(
    sdf: pd.DataFrame,
    bdf: pd.DataFrame,
    month: str,
    *,
    mom_threshold: float = DEFAULT_MOM_VARIANCE_THRESHOLD,
    qoq_threshold: float = DEFAULT_QOQ_VARIANCE_THRESHOLD,
    trailing_n: int = 3,
    as_of: date | None = None,
) -> dict[str, Any]:
    """MoM + trailing-quarter variance flags at parent level.

    Returns:
      month, mom_threshold, qoq_threshold, trailing_months,
      parent_table (DataFrame for selected month),
      mom_flags (list of dicts where |delta| >= mom_threshold),
      qoq_flags (list where |sum delta over trailing_n| >= qoq_threshold),
      qoq_table (parent × trailing months),
      caption, limitations, partial_month_note, as_of, incomplete_month
    """
    as_of = as_of or date.today()
    trailing = trailing_month_keys(month, trailing_n)
    parent_tbl = budget_vs_actual_table(
        sdf, bdf, month, level="parent", mom_threshold=mom_threshold, as_of=as_of
    )

    mom_flags: list[dict] = []
    if not parent_tbl.empty:
        for _, r in parent_tbl[parent_tbl["flagged"]].iterrows():
            mom_flags.append(
                {
                    "parent": r["parent"],
                    "budgeted": float(r["budgeted"]),
                    "actual": float(r["actual"]),
                    "delta": float(r["delta"]),
                    "abs_delta": float(r["abs_delta"]),
                    "month": month,
                    "kind": "mom",
                }
            )

    # Build per-month parent deltas for trailing window.
    # Skip the in-progress calendar month so partial underspend does not pollute QoQ.
    per_month: list[pd.DataFrame] = []
    for mk in trailing:
        if is_incomplete_budget_month(mk, as_of):
            continue
        t = budget_vs_actual_table(
            sdf, bdf, mk, level="parent", mom_threshold=mom_threshold, as_of=as_of
        )
        if t.empty:
            continue
        t = t[["parent", "delta", "budgeted", "actual"]].copy()
        t["month"] = mk
        per_month.append(t)

    qoq_flags: list[dict] = []
    qoq_table = pd.DataFrame()
    if per_month:
        long = pd.concat(per_month, ignore_index=True)
        # cumulative signed delta, then abs
        cum = long.groupby("parent", as_index=False).agg(
            cum_delta=("delta", "sum"),
            cum_budgeted=("budgeted", "sum"),
            cum_actual=("actual", "sum"),
            n_months=("month", "nunique"),
        )
        cum["abs_cum_delta"] = cum["cum_delta"].abs()
        thr_q = float(qoq_threshold)
        cum["flagged"] = cum["abs_cum_delta"] >= thr_q
        sav_mask = cum["parent"] == SAVINGS_FLUX_PARENT
        # Undersave-only for Transfers/Savings across the trailing window
        cum.loc[sav_mask, "flagged"] = cum.loc[sav_mask, "cum_delta"] <= -thr_q
        qoq_table = cum.sort_values("abs_cum_delta", ascending=False).reset_index(drop=True)
        for _, r in cum[cum["flagged"]].iterrows():
            qoq_flags.append(
                {
                    "parent": r["parent"],
                    "cum_delta": float(r["cum_delta"]),
                    "abs_cum_delta": float(r["abs_cum_delta"]),
                    "cum_budgeted": float(r["cum_budgeted"]),
                    "cum_actual": float(r["cum_actual"]),
                    "months": trailing,
                    "kind": "qoq",
                }
            )

    n_mom = len(mom_flags)
    n_qoq = len(qoq_flags)
    month_long = month_label_long(month)
    rng = friendly_month_range(trailing)
    mom_word = "category" if n_mom == 1 else "categories"
    qoq_word = "category" if n_qoq == 1 else "categories"
    if n_mom == 0:
        mom_part = f"{month_long}: on track this month."
    else:
        mom_part = (
            f"{month_long}: {n_mom} {mom_word} off plan by ${mom_threshold:,.0f}+."
        )
    if n_qoq == 0:
        qoq_part = f"Over {rng}, no category off by ${qoq_threshold:,.0f}+ combined."
    else:
        qoq_part = (
            f"Over {rng}, {n_qoq} {qoq_word} off by ${qoq_threshold:,.0f}+ combined."
        )
    caption = f"{mom_part} {qoq_part}"
    meta = {}
    partial_note = ""
    incomplete = is_incomplete_budget_month(month, as_of)
    if parent_tbl is not None and hasattr(parent_tbl, "attrs"):
        meta = parent_tbl.attrs.get("mortgage_extra_savings") or {}
        partial_note = str(parent_tbl.attrs.get("partial_month_note") or "")
    if not partial_note:
        partial_note = partial_month_flux_note(month, as_of)
    if partial_note:
        caption = f"{caption} {partial_note}"
    extra_note = str(meta.get("note") or "")
    if extra_note:
        caption = f"{caption} {extra_note}"
    excl_notes = flux_exclusion_notes(sdf, bdf, month)
    if excl_notes:
        caption = f"{caption} {' '.join(excl_notes)}"

    adhoc = unbudgeted_adhoc_flags(sdf, bdf, month)
    return {
        "month": month,
        "mom_threshold": float(mom_threshold),
        "qoq_threshold": float(qoq_threshold),
        "trailing_months": trailing,
        "parent_table": parent_tbl,
        "mom_flags": mom_flags,
        "unbudgeted_adhoc_flags": adhoc,
        "qoq_flags": qoq_flags,
        "qoq_table": qoq_table,
        "caption": caption,
        "limitations": BUDGET_LIMITATIONS_NOTE,
        "mortgage_extra_applied": float(meta.get("applied") or 0.0),
        "mortgage_extra_note": extra_note,
        "mortgage_extra_savings": meta,
        "exclusion_notes": excl_notes,
        "as_of": as_of,
        "incomplete_month": incomplete,
        "partial_month_note": partial_note,
    }


def format_flux_card(flag_dict: dict[str, Any]) -> dict[str, Any]:
    """Turn a this-month / 3-month flag into an attention-card payload.

    Returns icon, parent, line, badge, abs_delta, over, and ready-to-render html.
    """
    kind = str(flag_dict.get("kind") or "mom").lower()
    is_qoq = kind == "qoq"
    if is_qoq:
        actual = float(flag_dict.get("cum_actual") or 0.0)
        budgeted = float(flag_dict.get("cum_budgeted") or 0.0)
        delta = float(flag_dict.get("cum_delta") or flag_dict.get("delta") or 0.0)
        badge = "3-month"
    else:
        actual = float(flag_dict.get("actual") or 0.0)
        budgeted = float(flag_dict.get("budgeted") or 0.0)
        delta = float(flag_dict.get("delta") or 0.0)
        badge = "This month"

    abs_delta = abs(delta)
    over = delta > 0
    icon = "📈" if over else "📉"
    direction = "over" if over else "under"
    parent = str(flag_dict.get("parent") or "")
    line = (
        f"Spent ${actual:,.0f} · Plan was ${budgeted:,.0f} · "
        f"${abs_delta:,.0f} {direction}"
    )

    bg = "#fff7e6" if over else "#eef4ff"
    border = "#d9770655" if over else "#5b8def55"
    badge_bg = "#fde68a" if over else "#dbeafe"
    badge_fg = "#92400e" if over else "#1e3a8a"

    parent_e = html.escape(parent)
    line_e = html.escape(line)
    badge_e = html.escape(badge)
    card_html = (
        f'<div style="border-radius:14px;border:1px solid {border};background:{bg};'
        f'padding:0.75rem 0.9rem;min-height:7.2rem;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<div style="font-size:1.45rem;line-height:1;">{icon}</div>'
        f'<span style="font-size:0.68rem;font-weight:750;letter-spacing:0.04em;'
        f'text-transform:uppercase;background:{badge_bg};color:{badge_fg};'
        f'border-radius:999px;padding:0.18rem 0.55rem;">{badge_e}</span>'
        f"</div>"
        f'<div style="font-weight:750;font-size:1.12rem;color:#1f2937;'
        f'margin-top:0.35rem;">{parent_e}</div>'
        f'<div style="color:#4b5563;font-size:0.88rem;margin-top:0.25rem;'
        f'line-height:1.35;">{line_e}</div>'
        f"</div>"
    )
    return {
        "parent": parent,
        "icon": icon,
        "badge": badge,
        "kind": "qoq" if is_qoq else "mom",
        "delta": delta,
        "abs_delta": abs_delta,
        "actual": actual,
        "budgeted": budgeted,
        "over": over,
        "line": line,
        "html": card_html,
    }
