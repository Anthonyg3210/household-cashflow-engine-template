"""Calendar playbook helpers — day chips from projected flows.

Dashboard = am I OK / mitigations.
Calendar = which day each bill hits (effective day after planned overlays).
"""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .mitigation import category_nature, load_flexibility_config, parse_mitigation_source
from .project import Flow

_ROOT = Path(__file__).resolve().parent.parent
_CATEGORIES_PATH = _ROOT / "seed" / "categories.json"
_TAXONOMY_PATH = _ROOT / "data" / "taxonomy_v2.json"

# Visual buckets for the playbook calendar (calm, partner-friendly).
BUCKET_INCOME = "income"
BUCKET_FIXED = "fixed"
BUCKET_FLEXIBLE = "flexible"
BUCKET_LIFESTYLE = "lifestyle"
BUCKET_OTHER = "other"

_BUCKET_LABELS = {
    BUCKET_INCOME: "Income",
    BUCKET_FIXED: "Fixed / lights-on",
    BUCKET_FLEXIBLE: "Flexible / transfers",
    BUCKET_LIFESTYLE: "Memberships / lifestyle",
    BUCKET_OTHER: "Other",
}

_LIFESTYLE_KEYWORDS = (
    "netflix",
    "cricut",
    "youtube",
    "theme park",
    "park pass",
    "membership",
    "lawn",
    "pest",
    "car wash",
    "tommy",
    "dog",
    "cleaning",
    "cleanning",
    "presser",
    "pressure",
    "subscription",
    "hometeam",
)

_lifestyle_names_cache: Optional[set[str]] = None


def bucket_label(bucket: str) -> str:
    return _BUCKET_LABELS.get(bucket, bucket)


def load_lifestyle_category_names() -> set[str]:
    """Memberships / lifestyle names from seed categories + taxonomy Home Services & Subs."""
    global _lifestyle_names_cache
    if _lifestyle_names_cache is not None:
        return set(_lifestyle_names_cache)
    names: set[str] = set()
    if _CATEGORIES_PATH.is_file():
        with open(_CATEGORIES_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        items = raw if isinstance(raw, list) else raw.get("categories") or raw.get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            group = (it.get("group") or "").lower()
            section = (it.get("section") or "").lower()
            if group in ("memberships_subscriptions",) or "membership" in section:
                n = (it.get("name") or "").strip()
                if n and it.get("kind") != "section":
                    names.add(n)
    if _TAXONOMY_PATH.is_file():
        with open(_TAXONOMY_PATH, encoding="utf-8") as f:
            tax = json.load(f)
        for parent in tax.get("parents") or []:
            pid = (parent.get("id") or "").lower()
            pname = (parent.get("name") or "").lower()
            if pid in ("home_services", "entertainment") or "home services" in pname:
                for ch in parent.get("children") or []:
                    n = (ch.get("name") or "").strip()
                    if n:
                        names.add(n)
                    for ex in ch.get("excel") or []:
                        if ex:
                            names.add(str(ex).strip())
        for excel_name, meta in (tax.get("excel_name_to_new") or {}).items():
            parent = (meta.get("parent") or "").lower()
            if parent in ("home services & subs", "entertainment"):
                names.add(str(excel_name).strip())
    # Common spelling variants in rules
    names.update({"Video Stream", "Park Pass", "Home Cleaning", "Home Pressure Cleaning"})
    _lifestyle_names_cache = set(names)
    return set(names)


def clear_calendar_caches() -> None:
    global _lifestyle_names_cache
    _lifestyle_names_cache = None


def _flow_attrs(f: Any) -> tuple[str, float, str, str, str]:
    if isinstance(f, Flow):
        return f.category, float(f.amount), f.label or "", f.source or "", ""
    if isinstance(f, dict):
        return (
            str(f.get("category") or ""),
            float(f.get("amount") or 0),
            str(f.get("label") or ""),
            str(f.get("source") or ""),
            str(f.get("notes") or f.get("note") or ""),
        )
    return str(getattr(f, "category", "")), float(getattr(f, "amount", 0) or 0), str(
        getattr(f, "label", "") or ""
    ), str(getattr(f, "source", "") or ""), ""


def is_income_category(category: str, amount: float = 0.0) -> bool:
    """True for paychecks / income lines (not mitigation cancel credits)."""
    low = (category or "").lower()
    if "income" in low or category_nature(category) == "income_timing":
        return True
    if low in ("paycheck", "salary", "bonus"):
        return True
    if amount > 0:
        nature = category_nature(category)
        # Mitigation cancels are positive on expense categories
        if nature in ("flexible", "fixed"):
            return False
        if is_lifestyle_category(category):
            return False
    return False


def is_lifestyle_category(category: str, lifestyle_names: Optional[set[str]] = None) -> bool:
    name = (category or "").strip()
    names = lifestyle_names if lifestyle_names is not None else load_lifestyle_category_names()
    if name in names:
        return True
    low = name.lower()
    return any(k in low for k in _LIFESTYLE_KEYWORDS)


def calendar_bucket(
    category: str,
    amount: float = 0.0,
    *,
    flex_config: Optional[dict] = None,
    lifestyle_names: Optional[set[str]] = None,
) -> str:
    """Map a flow to a calendar visual bucket."""
    if is_income_category(category, amount):
        return BUCKET_INCOME
    if is_lifestyle_category(category, lifestyle_names):
        return BUCKET_LIFESTYLE
    nature = category_nature(category, flex_config)
    if nature == "income_timing" or (amount > 0 and "income" in (category or "").lower()):
        return BUCKET_INCOME
    if nature == "flexible":
        return BUCKET_FLEXIBLE
    if nature == "fixed":
        return BUCKET_FIXED
    # Heuristic leftovers
    low = (category or "").lower()
    if any(k in low for k in ("savings", "allowance", "transfer")):
        return BUCKET_FLEXIBLE
    if any(k in low for k in ("rocket", "mortgage", "insurance", "utility", "loan", "tuition", "fpl", "water")):
        return BUCKET_FIXED
    return BUCKET_OTHER


def _is_mitigation_move_flow(source: str, label: str, amount: float) -> bool:
    """True for the destination (or pull) leg of a mitigation overlay."""
    meta = parse_mitigation_source(source)
    if not meta:
        return "mitigation move" in (label or "").lower() or "mitigation pull" in (label or "").lower()
    kind = meta.get("kind") or ""
    if kind in ("move", "shift_flexible"):
        # Destination outflow is negative; cancel leg is positive
        return amount < 0
    if kind in ("income_pull", "pull_income"):
        # Destination income is positive
        return amount > 0
    return amount < 0


def effective_day_flows(
    flows: list[Any],
    *,
    flex_config: Optional[dict] = None,
    lifestyle_names: Optional[set[str]] = None,
) -> list[dict]:
    """Collapse rule+cancel pairs into net chips; mark mitigation-moved items.

    Same-category flows that net to ~0 (e.g. Savings rule −3500 + mitigation cancel +3500)
    are omitted so the calendar shows the *effective* day only.
    """
    cfg = flex_config or load_flexibility_config()
    life = lifestyle_names if lifestyle_names is not None else load_lifestyle_category_names()

    by_cat: dict[str, list[tuple[float, str, str, str]]] = {}
    for f in flows or []:
        cat, amt, label, source, notes = _flow_attrs(f)
        if not cat:
            continue
        by_cat.setdefault(cat, []).append((amt, label, source, notes))

    out: list[dict] = []
    for cat, parts in by_cat.items():
        net = sum(a for a, *_ in parts)
        if abs(net) < 0.005:
            continue
        moved = any(_is_mitigation_move_flow(src, lab, amt) for amt, lab, src, _ in parts)
        # Prefer a non-cancel label for notes
        notes_bits = []
        label_pick = ""
        sources = []
        for amt, lab, src, notes in parts:
            sources.append(src)
            if lab and "cancel" not in lab.lower():
                label_pick = label_pick or lab
            if notes:
                notes_bits.append(notes)
            if src.startswith("mitigation:") and amt * net > 0 and lab:
                label_pick = lab
        bucket = calendar_bucket(cat, net, flex_config=cfg, lifestyle_names=life)
        nature = category_nature(cat, cfg)
        if bucket == BUCKET_INCOME:
            nature_display = "income"
        elif bucket == BUCKET_LIFESTYLE:
            nature_display = "lifestyle"
        else:
            nature_display = nature if nature != "unknown" else bucket
        out.append(
            {
                "category": cat,
                "amount": net,
                "bucket": bucket,
                "bucket_label": bucket_label(bucket),
                "nature": nature_display,
                "moved": moved,
                "label": label_pick,
                "notes": "; ".join(notes_bits) if notes_bits else (label_pick if moved else ""),
                "sources": sources,
            }
        )

    # Income first, then fixed, lifestyle, flexible, other; larger |amount| within bucket
    order = {
        BUCKET_INCOME: 0,
        BUCKET_FIXED: 1,
        BUCKET_LIFESTYLE: 2,
        BUCKET_FLEXIBLE: 3,
        BUCKET_OTHER: 4,
    }
    out.sort(key=lambda r: (order.get(r["bucket"], 9), -abs(r["amount"]), r["category"]))
    return out


def short_chip_label(category: str, amount: float, *, max_len: int = 14) -> str:
    """Compact chip text, e.g. 'Savings' or 'Mortgage'."""
    name = (category or "").strip()
    # Short familiar aliases
    aliases = {
        "Home Mortgage": "Mortgage",
        "Alex's Income": "Alex",
        "Jordan's Income": "Jordan",
        "Partner Allowance": "Allowance",
        "Partner Allowance": "Allowance",
        "Student Loans": "Stu loans",
        "Car Insurance": "Car ins",
        "Park Pass": "Parks",
        "Car Wash Club": "Car wash",
        "YouTube Subscription": "YouTube",
        "Jordan's Craft Club": "Cricut",
        "Video Stream": "Netflix",
        "Home Cleaning": "Cleaning",
        "Homeowners Association Fee 1st": "HOA 1",
        "Homeowners Association Fee 2dn": "HOA 2",
        "Homeowners Maple Grove Dues": "HOA Maple",
    }
    text = aliases.get(name, name)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def chip_amount_text(amount: float) -> str:
    """Compact amount for chips: −$3.5k / +$4.5k / −$272."""
    sign = "+" if amount > 0 else "−" if amount < 0 else ""
    a = abs(amount)
    if a >= 1000:
        return f"{sign}${a / 1000:.1f}k".replace(".0k", "k")
    if a >= 100:
        return f"{sign}${a:.0f}"
    return f"{sign}${a:.2f}"


def month_days_index(daily: list[dict], year: int, month: int) -> dict[date, dict]:
    """Map date → daily row for one calendar month."""
    return {
        row["date"]: row
        for row in daily
        if row["date"].year == int(year) and row["date"].month == int(month)
    }


def available_calendar_months(daily: list[dict]) -> list[tuple[int, int]]:
    months = sorted({(d["date"].year, d["date"].month) for d in daily})
    return months


def month_bill_checklist(
    daily: list[dict],
    year: int,
    month: int,
    *,
    flex_config: Optional[dict] = None,
    lifestyle_names: Optional[set[str]] = None,
) -> list[dict]:
    """Chronological bill list for one month (effective flows after overlays).

    Each row: date, day, category, amount, bucket, bucket_label, nature, moved, notes.
    """
    rows: list[dict] = []
    for day_row in daily:
        d = day_row["date"]
        if d.year != int(year) or d.month != int(month):
            continue
        for ch in effective_day_flows(
            day_row.get("flows") or [],
            flex_config=flex_config,
            lifestyle_names=lifestyle_names,
        ):
            rows.append(
                {
                    "date": d,
                    "day": d.day,
                    "weekday": d.strftime("%a"),
                    "category": ch["category"],
                    "amount": ch["amount"],
                    "bucket": ch["bucket"],
                    "bucket_label": ch["bucket_label"],
                    "nature": ch["nature"],
                    "moved": bool(ch.get("moved")),
                    "notes": ch.get("notes") or ch.get("label") or "",
                }
            )
    rows.sort(key=lambda r: (r["date"], 0 if r["amount"] > 0 else 1, -abs(r["amount"]), r["category"]))
    return rows


def type_display_label(bucket: str, nature: str = "") -> str:
    """User-facing type for bills: fixed / flexible / membership (lifestyle)."""
    if bucket == BUCKET_INCOME or (nature or "") == "income":
        return "income"
    if bucket == BUCKET_LIFESTYLE or (nature or "") == "lifestyle":
        return "membership"
    if bucket == BUCKET_FLEXIBLE or (nature or "") == "flexible":
        return "flexible"
    if bucket == BUCKET_FIXED or (nature or "") == "fixed":
        return "fixed"
    return nature or bucket or "other"


def split_month_checklist(checklist: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split month_bill_checklist into (income_rows, bill_rows)."""
    income: list[dict] = []
    bills: list[dict] = []
    for r in checklist or []:
        if r.get("bucket") == BUCKET_INCOME or (
            float(r.get("amount") or 0) > 0 and (r.get("nature") or "") == "income"
        ):
            income.append(r)
        else:
            bills.append(r)
    return income, bills


def group_bills_by_day(bill_rows: list[dict]) -> list[tuple[date, list[dict]]]:
    """Chronological [(date, rows)] for spacious day sections."""
    by_day: dict[date, list[dict]] = {}
    order: list[date] = []
    for r in bill_rows or []:
        d = r["date"]
        if d not in by_day:
            by_day[d] = []
            order.append(d)
        by_day[d].append(r)
    for d in order:
        by_day[d].sort(key=lambda x: (-abs(float(x.get("amount") or 0)), x.get("category") or ""))
    return [(d, by_day[d]) for d in order]


def day_flow_counts(
    daily: list[dict],
    year: int,
    month: int,
    *,
    flex_config: Optional[dict] = None,
    lifestyle_names: Optional[set[str]] = None,
) -> dict[date, dict[str, int]]:
    """Sparse timing-map counts per day: income / bills / moved."""
    out: dict[date, dict[str, int]] = {}
    for day_row in daily:
        d = day_row["date"]
        if d.year != int(year) or d.month != int(month):
            continue
        chips = effective_day_flows(
            day_row.get("flows") or [],
            flex_config=flex_config,
            lifestyle_names=lifestyle_names,
        )
        if not chips:
            continue
        n_inc = sum(1 for c in chips if c["bucket"] == BUCKET_INCOME)
        n_bill = len(chips) - n_inc
        n_moved = sum(1 for c in chips if c.get("moved"))
        out[d] = {"income": n_inc, "bills": n_bill, "moved": n_moved, "total": len(chips)}
    return out


def month_money_totals(checklist: list[dict]) -> dict[str, float]:
    """Sum money-in (income) and money-out (absolute expenses) for hero cards."""
    income, bills = split_month_checklist(checklist)
    money_in = sum(float(r.get("amount") or 0) for r in income)
    money_out = sum(abs(float(r.get("amount") or 0)) for r in bills if float(r.get("amount") or 0) < 0)
    # rare positive non-income leftovers count toward neither hero
    return {
        "money_in": money_in,
        "money_out": money_out,
        "net": money_in - money_out,
        "income_count": len(income),
        "bill_count": len(bills),
        "moved_count": sum(1 for r in checklist if r.get("moved")),
    }


def month_week_lanes(year: int, month: int) -> list[dict]:
    """Sunday-start week strips for a calendar month.

    Each lane: {week_index, label, start, end, days: [date|None x 7]}.
    """
    first_wd, n_days = monthrange(year, month)
    start_pad = (first_wd + 1) % 7  # Monday=0 → Sunday-start pad
    cells: list[Optional[date]] = [None] * start_pad + [
        date(year, month, d) for d in range(1, n_days + 1)
    ]
    while len(cells) % 7:
        cells.append(None)
    lanes: list[dict] = []
    for wi, row_i in enumerate(range(0, len(cells), 7)):
        week_days = cells[row_i : row_i + 7]
        real = [d for d in week_days if d is not None]
        if not real:
            continue
        start_d, end_d = real[0], real[-1]
        if start_d.day == end_d.day:
            label = f"Week {wi + 1} · {start_d.strftime('%b')} {start_d.day}"
        else:
            label = f"Week {wi + 1} · {start_d.strftime('%b')} {start_d.day}–{end_d.day}"
        lanes.append(
            {
                "week_index": wi,
                "label": label,
                "start": start_d,
                "end": end_d,
                "days": week_days,
            }
        )
    return lanes


def checklist_for_dates(checklist: list[dict], days: list[date]) -> list[dict]:
    """Filter checklist rows to the given dates (order preserved)."""
    want = set(days)
    return [r for r in checklist if r.get("date") in want]


def pill_bucket_counts(chips: list[dict]) -> dict[str, int]:
    """Counts by visual bucket for a day's effective chips."""
    counts = {
        BUCKET_INCOME: 0,
        BUCKET_FIXED: 0,
        BUCKET_FLEXIBLE: 0,
        BUCKET_LIFESTYLE: 0,
        BUCKET_OTHER: 0,
        "moved": 0,
    }
    for c in chips or []:
        b = c.get("bucket") or BUCKET_OTHER
        if b not in counts:
            b = BUCKET_OTHER
        counts[b] += 1
        if c.get("moved"):
            counts["moved"] += 1
    return counts


def bifurcate_bill_rows(bill_rows: list[dict]) -> dict[str, list[dict]]:
    """Split bill rows into must_pay / flexible / membership / other for labeling."""
    buckets = {"must_pay": [], "flexible": [], "membership": [], "other": []}
    for r in bill_rows or []:
        typ = type_display_label(r.get("bucket") or "", r.get("nature") or "")
        if typ == "fixed":
            buckets["must_pay"].append(r)
        elif typ == "flexible":
            buckets["flexible"].append(r)
        elif typ == "membership":
            buckets["membership"].append(r)
        else:
            buckets["other"].append(r)
    return buckets


def week_playbook_sections(
    checklist: list[dict],
    year: int,
    month: int,
) -> list[dict]:
    """Week-first playbook sections: date range + days with income/bills.

    Each section:
      week_index, label, start, end,
      days: [{date, weekday, day, items, income, bills, must_pay, flexible, membership, other}]
    Empty days omitted. Items keep checklist order (income then bills by size).
    """
    lanes = month_week_lanes(year, month)
    sections: list[dict] = []
    for lane in lanes:
        day_list: list[dict] = []
        for d in lane["days"]:
            if d is None:
                continue
            rows = checklist_for_dates(checklist, [d])
            if not rows:
                continue
            income, bills = split_month_checklist(rows)
            parts = bifurcate_bill_rows(bills)
            day_list.append(
                {
                    "date": d,
                    "weekday": d.strftime("%A"),
                    "weekday_short": d.strftime("%a"),
                    "day": d.day,
                    "items": rows,
                    "income": income,
                    "bills": bills,
                    "must_pay": parts["must_pay"],
                    "flexible": parts["flexible"],
                    "membership": parts["membership"],
                    "other": parts["other"],
                }
            )
        sections.append(
            {
                "week_index": lane["week_index"],
                "label": lane["label"],
                "start": lane["start"],
                "end": lane["end"],
                "days": day_list,
                "item_count": sum(len(x["items"]) for x in day_list),
                "bill_count": sum(len(x["bills"]) for x in day_list),
                "income_count": sum(len(x["income"]) for x in day_list),
            }
        )
    return sections
