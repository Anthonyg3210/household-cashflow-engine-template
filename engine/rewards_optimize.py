"""Suggested credit cards for Rewards Card / Household family-card spend.

Scores editable card defs in data/rewards_cards.json against live
chase_black_card purchase actuals (is_card_purchase). Never freezes
scores — call score_family_card_spend() on each page render / after CSV
re-import so rankings refresh from the DB.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from engine.bank_import import is_card_purchase

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "data" / "rewards_cards.json"
IMPORT_META_PATH = ROOT / "data" / "black_card_import_meta.json"

BUCKETS = (
    "grocery",
    "dining",
    "gas",
    "streaming",
    "entertainment",
    "travel_hotel",
    "warehouse",
    "shopping_other",
)

BUCKET_LABELS = {
    "grocery": "Groceries / Publix",
    "dining": "Dining / Foxtail",
    "gas": "Gas / Costco Gas",
    "streaming": "Streaming",
    "entertainment": "Entertainment / parks",
    "travel_hotel": "Travel / hotel",
    "warehouse": "Costco (warehouse)",
    "shopping_other": "Everything else",
}

# Merchant / label cues (uppercase)
_GAS_RE = re.compile(
    r"COSTCO\s*GAS|SHELL|EXXON|CHEVRON|CIRCLE\s*K|CIRCLEK|MOBIL|BP\s|SUNOCO|WAWA|GAS\b",
    re.I,
)
_WAREHOUSE_RE = re.compile(r"COSTCO\s*WHSE|COSTCO\s*\*|COSTCO(?!\s*GAS)|BJ'?S\s*WHOLESALE|SAMS?\s*CLUB", re.I)
_STREAM_RE = re.compile(
    r"DISNEY\s*PLUS|NETFLIX|HULU|SPOTIFY|ROKU|HBO\s*MAX|\bHBO\b|PARAMOUNT\+|PEACOCK|"
    r"APPLE\.COM/BILL|YOUTUBE\s*PREMIUM|AMAZON\s*PRIME|AMC\s*GLOBAL|CBS\s*INTERACTIVE|"
    r"ROKU\s+FOR",
    re.I,
)
_HOTEL_RE = re.compile(
    r"MARRIOTT|TRAVELPOINTS|PAN\s*PACIFIC|GAYLORD|HILTON|HYATT|HOTEL|RESORT|AIRBNB|VRBO",
    re.I,
)
_MARRIOTT_RE = re.compile(r"MARRIOTT|TRAVELPOINTS|GAYLORD", re.I)
_TRAVEL_RE = re.compile(
    r"AIRLINE|UNITED\s|DELTA\s|AMERICAN\s*AIR|JETBLUE|SOUTHWEST|AIRPORT|"
    r"DCL\s*SHIP|CRUISE|EXPEDIA|BOOKING\.COM|CHASE\s*TRAVEL",
    re.I,
)
_AUTO_DEALER_RE = re.compile(
    r"\bKIA\b|\bFORD\b|\bTOYOTA\b|\bHONDA\b|\bCHEVROLET\b|\bBMW\b|DEALER|BONIFACE",
    re.I,
)
_GROCERY_PARENTS = {"Groceries"}
_DINING_PARENTS = {"Dining"}
_GAS_PARENTS = {"Transportation"}
_ENT_PARENTS = {"Entertainment"}
_STREAM_SUBS = {"Other Subscriptions"}
# Theme-park / Disney memberships → entertainment for rewards (not grocery)
_ENT_SUBS = {"Theme Parks", "Family Outings"}
_DINING_RE = re.compile(
    r"FOXTAIL|CHICK-FIL-A|CHICKFILA|PAPA\s*JOHN|MOE'?S|WENDY|PANERA|BONEFISH|"
    r"FIRST\s*WATCH|STARBUCKS|DUNKIN|MCDONALD|TACO\s*BELL|CHIPOTLE|JERSEY\s*MIKE|"
    r"NOTHING\s*BUNDT|CRUMBL|GRILL|RESTAURANT|CAFE|COFFEE",
    re.I,
)
_GAS_EXTRA_RE = re.compile(r"MURPHY|7-ELEVEN|7ELEVEN|WAWA", re.I)


def load_card_defs(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or CARDS_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cards" not in data:
        raise ValueError(f"Invalid rewards cards file: {path}")
    return data


def load_import_meta(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or IMPORT_META_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_import_meta(payload: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    """Persist CSV import stamp so UI can show 'CSV refreshed …'."""
    path = path or IMPORT_META_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_import_meta(path)
    existing.update(payload)
    existing["saved_at"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return existing


def _parse_date(val) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _label_upper(row: dict) -> str:
    return (row.get("label") or "").upper()


def is_one_off(row: dict, defs: dict[str, Any]) -> bool:
    """Auto-dealer / large one-off purchases excluded from typical-month scoring."""
    lab = _label_upper(row)
    spend = abs(float(row.get("amount") or 0))
    patterns = defs.get("one_off_exclude_patterns") or []
    for p in patterns:
        if p and p.upper() in lab:
            return True
    min_amt = float(defs.get("one_off_auto_dealer_min") or 2000.0)
    if spend >= min_amt and _AUTO_DEALER_RE.search(lab):
        return True
    return False


def classify_rewards_bucket(row: dict) -> str:
    """Map a rewards-card purchase into a rewards bucket."""
    lab = _label_upper(row)
    parent = (row.get("parent") or "").strip()
    sub = (row.get("subcategory") or "").strip()

    # Gas before warehouse (COSTCO GAS vs COSTCO WHSE)
    if (
        _GAS_RE.search(lab)
        or _GAS_EXTRA_RE.search(lab)
        or (parent in _GAS_PARENTS and "Gas" in sub)
    ):
        return "gas"
    if _WAREHOUSE_RE.search(lab) or (parent == "Groceries" and sub in ("Costco", "BJ's", "Sam's Club")):
        # Costco Gas already returned; Costco WHSE / membership → warehouse
        if "GAS" in lab:
            return "gas"
        return "warehouse"
    if _STREAM_RE.search(lab) or (parent == "Home Services & Subs" and sub in _STREAM_SUBS):
        # Disney Plus lives under Theme Parks in taxonomy — still streaming
        if re.search(r"DISNEY\s*PLUS", lab, re.I):
            return "streaming"
        if sub in _STREAM_SUBS or _STREAM_RE.search(lab):
            return "streaming"
    if _HOTEL_RE.search(lab) or _TRAVEL_RE.search(lab):
        return "travel_hotel"
    if parent in _DINING_PARENTS or _DINING_RE.search(lab):
        return "dining"
    if parent in _GROCERY_PARENTS:
        # Target/Walmart/Publix grocery coding
        return "grocery"
    if parent in _ENT_PARENTS or sub in _ENT_SUBS:
        return "entertainment"
    if parent == "Home Services & Subs" and sub == "Theme Parks":
        return "entertainment"
    return "shopping_other"


def _purchase_rows(actuals: Iterable[dict], *, source: str = "chase_black_card") -> list[dict]:
    out = []
    for a in actuals:
        if (a.get("source") or "") != source:
            continue
        amt = float(a.get("amount") or 0)
        txn = a.get("txn_type") or ""
        if not is_card_purchase(txn, amt):
            continue
        spend = abs(amt) if amt < 0 else 0.0
        if spend <= 0:
            continue
        out.append(a)
    return out


def _annualize_factor(dates: list[date]) -> tuple[float, str, date, date, int]:
    """Return (factor to annual $, method doc, min_d, max_d, n_days)."""
    if not dates:
        today = date.today()
        return 1.0, "no_purchases", today, today, 0
    dmin, dmax = min(dates), max(dates)
    n_days = max(1, (dmax - dmin).days + 1)
    span_months = n_days / 30.4375
    # Prefer trailing ~12 months window when span is long enough
    trail_start = dmax - timedelta(days=365)
    if dmin <= trail_start + timedelta(days=14) and n_days >= 300:
        method = (
            "trailing_~12_months: annual ≈ sum of purchases in the last 365 days "
            f"(through {dmax.isoformat()})"
        )
        return 1.0, method, dmin, dmax, n_days
    # Short span: scale up from observed window
    factor = 365.0 / float(n_days)
    method = (
        f"annualized_from_csv_span: sum × 365/{n_days} "
        f"({dmin.isoformat()} → {dmax.isoformat()}, ~{span_months:.1f} mo)"
    )
    return factor, method, dmin, dmax, n_days


def aggregate_bucket_spend(
    purchases: list[dict],
    defs: dict[str, Any],
    *,
    exclude_one_offs: bool = True,
) -> dict[str, Any]:
    """Classify + annualize spend by rewards bucket from live purchase rows."""
    rows = []
    one_off_spend = 0.0
    one_off_labels: list[str] = []
    for a in purchases:
        if exclude_one_offs and is_one_off(a, defs):
            one_off_spend += abs(float(a.get("amount") or 0))
            one_off_labels.append((a.get("label") or "")[:48])
            continue
        d = _parse_date(a.get("date"))
        if d is None:
            continue
        bucket = classify_rewards_bucket(a)
        spend = abs(float(a.get("amount") or 0))
        rows.append({"date": d, "bucket": bucket, "spend": spend, "label": a.get("label") or ""})

    if not rows:
        empty = {b: 0.0 for b in BUCKETS}
        empty_annual = dict(empty)
        empty_annual["marriott_hotel"] = 0.0
        return {
            "raw_by_bucket": dict(empty),
            "annual_by_bucket": empty_annual,
            "annual_total": 0.0,
            "raw_total": 0.0,
            "factor": 1.0,
            "method": "no_purchases",
            "date_min": None,
            "date_max": None,
            "n_days": 0,
            "n_purchases": 0,
            "one_off_spend_excluded": round(one_off_spend, 2),
            "one_off_labels": one_off_labels[:5],
            "exclude_one_offs": exclude_one_offs,
        }

    dates = [r["date"] for r in rows]
    dmax = max(dates)
    dmin = min(dates)
    n_days = max(1, (dmax - dmin).days + 1)
    trail_start = dmax - timedelta(days=365)
    use_trailing = dmin <= trail_start + timedelta(days=14) and n_days >= 300

    raw = {b: 0.0 for b in BUCKETS}
    marriott_raw = 0.0
    if use_trailing:
        window = [r for r in rows if r["date"] >= trail_start]
        factor = 1.0
        method = (
            "trailing_~12_months: annual ≈ sum of purchases in the last 365 days "
            f"(through {dmax.isoformat()})"
        )
    else:
        window = rows
        factor = 365.0 / float(n_days)
        span_months = n_days / 30.4375
        method = (
            f"annualized_from_csv_span: sum × 365/{n_days} "
            f"({dmin.isoformat()} → {dmax.isoformat()}, ~{span_months:.1f} mo)"
        )

    for r in window:
        raw[r["bucket"]] = raw.get(r["bucket"], 0.0) + r["spend"]
        if r["bucket"] == "travel_hotel" and _MARRIOTT_RE.search(r.get("label") or ""):
            marriott_raw += r["spend"]

    annual = {b: round(raw[b] * factor, 2) for b in BUCKETS}
    annual["marriott_hotel"] = round(marriott_raw * factor, 2)
    return {
        "raw_by_bucket": {b: round(raw[b], 2) for b in BUCKETS},
        "annual_by_bucket": annual,
        "annual_total": round(sum(annual[b] for b in BUCKETS), 2),
        "raw_total": round(sum(raw.values()), 2),
        "factor": round(factor, 4),
        "method": method,
        "date_min": dmin.isoformat(),
        "date_max": dmax.isoformat(),
        "n_days": n_days,
        "n_purchases": len(window),
        "one_off_spend_excluded": round(one_off_spend, 2),
        "one_off_labels": one_off_labels[:5],
        "exclude_one_offs": exclude_one_offs,
    }


def _pct_rewards(spend: float, pct: float) -> float:
    return spend * pct


def _mult_rewards(spend: float, mult: float, cpp_cents: float) -> float:
    # points = spend * mult; dollars = points * (cpp_cents/100)
    return spend * mult * (cpp_cents / 100.0)


def score_card(card: dict[str, Any], annual: dict[str, float]) -> dict[str, Any]:
    """Estimate effective annual rewards $ for one card vs annualized bucket spend."""
    earn = card.get("earn") or {}
    etype = earn.get("type")
    fee = float(card.get("annual_fee") or 0)
    cpp = float(card.get("cpp_cents") or 1.0)
    g = float(annual.get("grocery") or 0)
    d = float(annual.get("dining") or 0)
    gas = float(annual.get("gas") or 0)
    stream = float(annual.get("streaming") or 0)
    ent = float(annual.get("entertainment") or 0)
    travel = float(annual.get("travel_hotel") or 0)
    wh = float(annual.get("warehouse") or 0)
    other = float(annual.get("shopping_other") or 0)
    total = g + d + gas + stream + ent + travel + wh + other

    rewards = 0.0
    why_bits: list[str] = []

    if etype == "marriott_boundless":
        marriott_spend = float(annual.get("marriott_hotel") or 0)
        other_travel = max(0.0, travel - marriott_spend)
        rewards += _mult_rewards(marriott_spend, float(earn["marriott_hotels_mult"]), cpp)
        combo = g + gas + d
        cap = float(earn["grocery_gas_dining_cap"])
        first = min(combo, cap)
        after = max(0.0, combo - cap)
        rewards += _mult_rewards(first, float(earn["grocery_gas_dining_mult_first"]), cpp)
        rewards += _mult_rewards(after, float(earn["grocery_gas_dining_mult_after"]), cpp)
        rest = stream + ent + wh + other + other_travel
        rewards += _mult_rewards(rest, float(earn["else_mult"]), cpp)
        why_bits.append("3x groceries/gas/dining (cap) + 2x else; 6x Marriott hotels")

    elif etype == "csr":
        rewards += _mult_rewards(travel, float(earn["flights_hotels_direct_mult"]), cpp)
        rewards += _mult_rewards(d, float(earn["dining_mult"]), cpp)
        rest = g + gas + stream + ent + wh + other
        rewards += _mult_rewards(rest, float(earn["else_mult"]), cpp)
        why_bits.append("3x dining + 4x hotels; high AF")

    elif etype == "amex_gold":
        din_cap = float(earn["dining_cap"])
        sm_cap = float(earn["supermarket_cap"])
        # Supermarkets ≈ grocery only (not warehouse — Costco often declines Amex)
        din = min(d, din_cap)
        sm = min(g, sm_cap)
        rewards += _mult_rewards(din, float(earn["dining_mult"]), cpp)
        rewards += _mult_rewards(sm, float(earn["supermarket_mult"]), cpp)
        rest = (d - din) + (g - sm) + gas + stream + ent + travel + wh + other
        rewards += _mult_rewards(rest, float(earn["else_mult"]), cpp)
        why_bits.append("4x Publix/dining; Costco often no Amex")

    elif etype == "amex_bcp":
        sm_cap = float(earn["supermarket_cap"])
        sm_first = min(g, sm_cap)
        sm_after = max(0.0, g - sm_cap)
        rewards += _pct_rewards(sm_first, float(earn["supermarket_pct_first"]))
        rewards += _pct_rewards(sm_after, float(earn["supermarket_pct_after"]))
        rewards += _pct_rewards(stream, float(earn["streaming_pct"]))
        rewards += _pct_rewards(gas, float(earn["gas_pct"]))
        rest = d + ent + travel + wh + other
        rewards += _pct_rewards(rest, float(earn["else_pct"]))
        why_bits.append("6% groceries (first $6k) + 3% gas")

    elif etype == "citi_custom_cash":
        eligible = set(earn.get("eligible_buckets") or [])
        # Pick top eligible annual bucket; 5% on first $500/cycle × 12
        best_b = None
        best_amt = -1.0
        for b in eligible:
            amt = float(annual.get(b) or 0)
            if amt > best_amt:
                best_amt = amt
                best_b = b
        cap_yr = float(earn["bonus_cap_per_cycle"]) * float(earn.get("cycles_per_year") or 12)
        bonus_base = min(max(best_amt, 0.0), cap_yr)
        rewards += _pct_rewards(bonus_base, float(earn["bonus_pct"]))
        # Remainder of that bucket + all other spend at 1%
        remainder = total - bonus_base
        rewards += _pct_rewards(max(0.0, remainder), float(earn["else_pct"]))
        label = BUCKET_LABELS.get(best_b or "", best_b or "top category")
        why_bits.append(f"5% on {label} (first ${cap_yr:,.0f}/yr)")

    elif etype == "flat_pct":
        rewards += _pct_rewards(total, float(earn["pct"]))
        why_bits.append(f'{float(earn["pct"]) * 100:.0f}% flat')

    elif etype == "flat_mult":
        rewards += _mult_rewards(total, float(earn["mult"]), cpp)
        why_bits.append(f'{float(earn["mult"]):.0f}x everywhere')

    elif etype == "cap1_savor":
        # Grocery excluding Walmart/Target — we don't split at aggregate; assume
        # most Household grocery is Publix/Costco-gas-elsewhere. Apply 3% to grocery
        # but note Target/Walmart exclusion; warehouse is NOT grocery for Savor.
        bonus_buckets = set(earn.get("bonus_buckets") or [])
        bonus_spend = 0.0
        for b in bonus_buckets:
            if b == "grocery":
                bonus_spend += g  # Publix-heavy; Target share is small
            else:
                bonus_spend += float(annual.get(b) or 0)
        else_spend = total - bonus_spend
        # warehouse + shopping_other + gas + travel stay at 1% if not in bonus
        rewards += _pct_rewards(bonus_spend, float(earn["bonus_pct"]))
        rewards += _pct_rewards(max(0.0, else_spend), float(earn["else_pct"]))
        why_bits.append("3% grocery/dining/entertainment/streaming")

    else:
        rewards += _pct_rewards(total, 0.01)
        why_bits.append("fallback 1%")

    net = rewards - fee
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "short_name": card.get("short_name") or card.get("name"),
        "annual_fee": fee,
        "gross_rewards": round(rewards, 2),
        "net_value": round(net, 2),
        "cpp_cents": cpp,
        "cpp_label": card.get("cpp_label") or "",
        "network": card.get("network") or "",
        "accepts_costco": bool(card.get("accepts_costco", True)),
        "why": "; ".join(why_bits),
        "notes": card.get("notes") or "",
        "current_product_note": card.get("current_product_note") or "",
    }


def _best_card_for_bucket(
    bucket: str,
    scored: list[dict[str, Any]],
    cards_by_id: dict[str, dict],
) -> dict[str, str]:
    """Pick a practical 'pay with' card for one spend bucket."""
    # Prefer category bonus cards that accept Costco when needed
    ranked = sorted(scored, key=lambda c: c["net_value"], reverse=True)

    def _find(*ids: str) -> Optional[dict]:
        for i in ids:
            for c in ranked:
                if c["id"] == i:
                    return c
        return None

    if bucket == "grocery":
        # BCP 6% groceries wins if Amex OK at Publix; Custom Cash / Savor backups
        c = _find("amex_bcp", "citi_custom_cash", "cap1_savor", "amex_gold")
        why = "Highest grocery earn on Publix-style spend"
    elif bucket == "warehouse":
        # Amex often declined at Costco — prefer Visa/MC 2%+ or Custom Cash
        c = _find("citi_custom_cash", "citi_double_cash", "cap1_venture_x", "marriott_boundless")
        why = "Costco rarely takes Amex — use Visa/MC (2%+ or 5% if it codes grocery)"
    elif bucket == "dining":
        c = _find("amex_gold", "chase_sapphire_reserve", "cap1_savor", "citi_custom_cash")
        why = "Dining bonus category"
    elif bucket == "gas":
        c = _find("amex_bcp", "citi_custom_cash", "marriott_boundless", "citi_double_cash")
        why = "Gas bonus (Costco Gas / Circle K)"
    elif bucket == "streaming":
        c = _find("amex_bcp", "cap1_savor", "citi_custom_cash")
        why = "Streaming bonus"
    elif bucket == "entertainment":
        c = _find("cap1_savor", "citi_custom_cash", "citi_double_cash")
        why = "Entertainment / parks bonus when available"
    elif bucket == "travel_hotel":
        c = _find("marriott_boundless", "chase_sapphire_reserve", "cap1_venture_x")
        why = "Hotel / travel multipliers (Marriott 6x on Boundless)"
    else:
        c = _find("citi_double_cash", "cap1_venture_x", "marriott_boundless")
        why = "Flat 2% catch-all"
    if c is None and ranked:
        c = ranked[0]
    return {
        "bucket": bucket,
        "bucket_label": BUCKET_LABELS.get(bucket, bucket),
        "best_card": (c or {}).get("short_name") or (c or {}).get("name") or "—",
        "best_card_id": (c or {}).get("id") or "",
        "why": why,
    }


def build_playbook(scored: list[dict[str, Any]], cards: list[dict]) -> list[dict[str, str]]:
    by_id = {c["id"]: c for c in cards}
    order = ["grocery", "warehouse", "dining", "gas", "shopping_other"]
    return [_best_card_for_bucket(b, scored, by_id) for b in order]


def score_family_card_spend(
    actuals: Iterable[dict],
    *,
    cards_path: Optional[Path] = None,
    exclude_one_offs: bool = True,
    top_n: int = 4,
) -> dict[str, Any]:
    """Live score from chase_black_card actuals — call on every page load.

    Returns a UI-ready dict: top recommendations, playbook, bucket annuals,
    as-of / CSV-refreshed captions. No cached score snapshot.
    """
    defs = load_card_defs(cards_path)
    purchases = _purchase_rows(actuals)
    agg = aggregate_bucket_spend(purchases, defs, exclude_one_offs=exclude_one_offs)
    agg_with = aggregate_bucket_spend(purchases, defs, exclude_one_offs=False)

    scored = [score_card(c, agg["annual_by_bucket"]) for c in defs["cards"]]
    scored.sort(key=lambda c: c["net_value"], reverse=True)
    scored_with = [score_card(c, agg_with["annual_by_bucket"]) for c in defs["cards"]]
    scored_with.sort(key=lambda c: c["net_value"], reverse=True)

    playbook = build_playbook(scored, defs["cards"])
    meta = load_import_meta()
    rates_as_of = defs.get("as_of") or ""
    purch_through = agg.get("date_max")
    csv_refreshed = meta.get("imported_at") or meta.get("saved_at") or ""

    top = scored[: max(1, top_n)]
    for i, c in enumerate(top):
        c["rank"] = i + 1

    return {
        "as_of_rates": rates_as_of,
        "purchases_through": purch_through,
        "purchases_from": agg.get("date_min"),
        "csv_refreshed_at": csv_refreshed,
        "computed_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "annualize_method": agg["method"],
        "exclude_one_offs": exclude_one_offs,
        "one_off_spend_excluded": agg["one_off_spend_excluded"],
        "one_off_labels": agg["one_off_labels"],
        "buckets_annual": agg["annual_by_bucket"],
        "buckets_annual_with_one_offs": agg_with["annual_by_bucket"],
        "annual_spend": agg["annual_total"],
        "annual_spend_with_one_offs": agg_with["annual_total"],
        "n_purchases": agg["n_purchases"],
        "recommendations": top,
        "all_scores": scored,
        "all_scores_with_one_offs": scored_with,
        "playbook": playbook,
        "current_card_id": "marriott_boundless",
        "caption": _format_caption(rates_as_of, purch_through, csv_refreshed, agg),
    }


def _format_caption(
    rates_as_of: str,
    purch_through: Optional[str],
    csv_refreshed: str,
    agg: dict[str, Any],
) -> str:
    bits = []
    if purch_through:
        try:
            d = date.fromisoformat(str(purch_through)[:10])
            bits.append(f"Based on purchases through {d.strftime('%b %-d, %Y')}")
        except ValueError:
            bits.append(f"Based on purchases through {purch_through}")
    if csv_refreshed:
        try:
            # accept ISO with Z
            raw = str(csv_refreshed).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            bits.append(f"CSV refreshed {dt.strftime('%b %-d, %Y')}")
        except ValueError:
            bits.append(f"CSV refreshed {csv_refreshed[:10]}")
    else:
        bits.append("scores recompute from live DB on every refresh (no frozen snapshot)")
    tail = (
        f"Rates as of {rates_as_of}. Not advice — terms change. "
        "Costco often declines Amex. "
        f"Annualize: {agg.get('method', '')}."
    )
    head = " · ".join(bits) if bits else "Live from chase_black_card actuals"
    return f"{head}. {tail}"


def format_refresh_line(result: dict[str, Any]) -> str:
    """Short UI line: purchases through … · CSV refreshed …"""
    parts = []
    pt = result.get("purchases_through")
    if pt:
        try:
            d = date.fromisoformat(str(pt)[:10])
            parts.append(f"Based on purchases through {d.strftime('%b %-d, %Y')}")
        except ValueError:
            parts.append(f"Based on purchases through {pt}")
    cr = result.get("csv_refreshed_at") or ""
    if cr:
        try:
            raw = str(cr).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            parts.append(f"CSV refreshed {dt.strftime('%b %-d, %Y')}")
        except ValueError:
            parts.append(f"CSV refreshed {str(cr)[:10]}")
    else:
        parts.append("recomputed live from DB (import to stamp CSV refreshed date)")
    return " · ".join(parts)
