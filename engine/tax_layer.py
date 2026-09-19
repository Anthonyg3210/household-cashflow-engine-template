"""Retirement TAX LAYER — MFJ 2026 bracket math + Roth conversion scenarios.

Does NOT replace Retirement OS. Does NOT touch Floor / Comfort / Life math.
Reads data/tax_profile.json (and optionally tax_history.jsonl for prior-year
context). All figures are planning estimates, not a tax return.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
TAX_PROFILE_PATH = _ROOT / "data" / "tax_profile.json"
TAX_HISTORY_PATH = _ROOT / "data" / "tax_history.jsonl"
PLAN_FEATURES_PATH = _ROOT / "data" / "plan_features.json"


def profile_path() -> Path:
    return TAX_PROFILE_PATH


def history_path() -> Path:
    return TAX_HISTORY_PATH


def load_tax_profile(path: Optional[Path] = None) -> dict[str, Any]:
    """Load tax_profile.json (MFJ unit, 2026 brackets, stub annualization)."""
    p = path or TAX_PROFILE_PATH
    with open(p, encoding="utf-8") as f:
        return json.load(f)



def load_plan_features(path: Optional[Path] = None) -> dict[str, Any]:
    """Load data/plan_features.json (Northstar Tech SPD — one file for all employer accounts)."""
    p = path or PLAN_FEATURES_PATH
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def live_401k_pre_tax_balance(profile: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Pre-tax 401k / BrokerageLink balance for conversion sizing.

    Prefers the live Retirement warehouse (`current_retirement_assets`), then
    falls back to tax_profile.json. Analysis updates when that balance updates.
    """
    prof = profile if profile is not None else load_tax_profile()
    source = "tax_profile.json"
    bal = float((prof.get("brokeragelink") or {}).get("balance") or 0.0)
    as_of = (prof.get("brokeragelink") or {}).get("as_of") or prof.get("as_of")
    try:
        from engine.retirement import current_retirement_assets

        assets = current_retirement_assets()
        live = float(assets.get("brokeragelink") or 0.0)
        if live > 0:
            bal = live
            source = "retirement_accounts / current_retirement_assets"
            as_of = assets.get("as_of") or as_of
    except Exception:
        pass
    return {
        "balance": round(bal, 2),
        "source": source,
        "as_of": as_of,
        "tax_character": (prof.get("brokeragelink") or {}).get("tax_character")
        or "pre-tax traditional 401k (BrokerageLink)",
    }



def load_tax_history(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Load tax_history.jsonl (one JSON object per prior year)."""
    p = path or TAX_HISTORY_PATH
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def irs_2026_mfj(profile: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return 2026 MFJ standard deduction + brackets from profile."""
    prof = profile if profile is not None else load_tax_profile()
    block = dict(prof.get("irs_2026_mfj") or {})
    if "standard_deduction" not in block or "brackets" not in block:
        raise ValueError("tax_profile missing irs_2026_mfj.standard_deduction / brackets")
    return block


def _brackets(profile: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    return list(irs_2026_mfj(profile)["brackets"])


def compute_tax(
    taxable_income: float,
    profile: Optional[dict[str, Any]] = None,
) -> float:
    """Progressive federal income tax dollars on taxable income (MFJ 2026).

    Uses profile bracket maxes as inclusive upper bounds. Top bracket (max=null)
    taxes all remaining income at that rate. No credits, SE tax, or NIIT.
    """
    taxable = max(0.0, float(taxable_income))
    tax = 0.0
    prev_cap = 0.0
    for b in _brackets(profile):
        rate = float(b["rate"])
        cap = b.get("max")
        if cap is None:
            if taxable > prev_cap:
                tax += (taxable - prev_cap) * rate
            break
        upper = float(cap)
        if taxable <= prev_cap:
            break
        slice_amt = min(taxable, upper) - prev_cap
        if slice_amt > 0:
            tax += slice_amt * rate
        prev_cap = upper
    return round(tax, 2)


def _bracket_label(rate: float) -> str:
    pct = rate * 100.0
    if abs(pct - round(pct)) < 1e-9:
        return f"{int(round(pct))}%"
    return f"{pct:.1f}%"


def marginal_bracket_info(
    taxable: float,
    profile: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Marginal rate, room to next bracket top, and label for taxable income.

    room_to_next: dollars of additional taxable income that stay in the current
    bracket (to the inclusive max). None if already in the top bracket.
    """
    t = max(0.0, float(taxable))
    brackets = _brackets(profile)
    prev_cap = 0.0
    for b in brackets:
        rate = float(b["rate"])
        cap = b.get("max")
        label = _bracket_label(rate)
        if cap is None:
            return {
                "rate": rate,
                "label": label,
                "bracket_label": label,
                "min": prev_cap + (0.0 if prev_cap == 0 else 0.0),
                "max": None,
                "room_to_next": None,
                "taxable": t,
            }
        upper = float(cap)
        # In this bracket if taxable <= upper (and > previous upper, or zero).
        if t <= upper:
            room = max(0.0, upper - t)
            return {
                "rate": rate,
                "label": label,
                "bracket_label": label,
                "min": float(b.get("min") or (0 if prev_cap == 0 else prev_cap + 1)),
                "max": upper,
                "room_to_next": round(room, 2),
                "taxable": t,
            }
        prev_cap = upper
    # Fallback (should not reach)
    last = brackets[-1]
    return {
        "rate": float(last["rate"]),
        "label": _bracket_label(float(last["rate"])),
        "bracket_label": _bracket_label(float(last["rate"])),
        "min": float(last.get("min") or 0),
        "max": last.get("max"),
        "room_to_next": None,
        "taxable": t,
    }


def _next_bracket_after(
    rate: float,
    profile: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    brackets = _brackets(profile)
    for i, b in enumerate(brackets):
        if abs(float(b["rate"]) - float(rate)) < 1e-12:
            if i + 1 < len(brackets):
                return brackets[i + 1]
            return None
    return None


def build_base_taxable_2026(
    profile: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a simple 2026 MFJ taxable-income proxy for conversion planning.

    Method (documented — intentionally simple, not a full Form 1040):
      pretax_401k_annualized = ytd_401k * 26 / pays_to_date_assumed
      AGI_proxy = alex annualized_gross_base
                 + secondary_flat_annual
                 - pretax_401k_annualized
      taxable_proxy = max(0, AGI_proxy - standard_deduction_2026)

    Notes / caveats baked into the return dict:
    - Uses stub annualized_gross_base (YTD × 26/18), not salary-rate alone.
    - Jordan = flat $18,000 operating model (not prior-year Sch C profit).
    - Only employee 401k pretax is subtracted; other pretax (HSA/medical/dental)
      is NOT removed here — so AGI_proxy is a bit high vs true AGI. Good enough
      for bracket / conversion room estimates.
    - No child tax credit, SE tax, QBI, or adjustments beyond the 401k proxy.
    - Florida state income tax = $0.
    """
    prof = profile if profile is not None else load_tax_profile()
    stub = prof.get("current_year_stub") or {}
    ann = stub.get("annualization") or {}
    jordan = prof.get("secondary_flat_2026") or {}
    irs = irs_2026_mfj(prof)
    pretax = stub.get("pretax_401k") or {}

    alex_gross = float(ann.get("annualized_gross_base") or 0.0)
    secondary_flat = float(jordan.get("annual") or 0.0)
    ytd_401k = float(pretax.get("ytd") or 0.0)
    pays = float(ann.get("pays_to_date_assumed") or 18)
    # Current period 401k is $0; still annualize YTD at 26/pays so remaining-year
    # deferral is not assumed zero just because this stub line was $0.
    pretax_401k_annualized = ytd_401k * (26.0 / pays) if pays > 0 else ytd_401k
    std_ded = float(irs["standard_deduction"])

    agi_proxy = alex_gross + secondary_flat - pretax_401k_annualized
    taxable_proxy = max(0.0, agi_proxy - std_ded)

    fed_taxable_ann = float(ann.get("annualized_fed_taxable_base") or 0.0)
    margin = marginal_bracket_info(taxable_proxy, prof)
    base_tax = compute_tax(taxable_proxy, prof)
    effective = (base_tax / taxable_proxy) if taxable_proxy > 0 else 0.0
    effective_on_agi = (base_tax / agi_proxy) if agi_proxy > 0 else 0.0
    _bl_live = live_401k_pre_tax_balance(prof)

    return {
        "model_year": int(prof.get("model_year") or 2026),
        "filing_status": prof.get("filing_status") or "MFJ",
        "state": prof.get("state") or "FL",
        "state_income_tax": float(prof.get("state_income_tax") or 0.0),
        "alex_annualized_gross_base": round(alex_gross, 2),
        "secondary_flat_annual": round(secondary_flat, 2),
        "ytd_401k": round(ytd_401k, 2),
        "pays_to_date_assumed": pays,
        "pretax_401k_annualized": round(pretax_401k_annualized, 2),
        "agi_proxy": round(agi_proxy, 2),
        "standard_deduction": std_ded,
        "taxable_proxy": round(taxable_proxy, 2),
        "taxable_base": round(taxable_proxy, 2),
        "base_tax": base_tax,
        "effective_rate_on_taxable": round(effective, 6),
        "effective_rate_on_agi": round(effective_on_agi, 6),
        "marginal": margin,
        "annualized_fed_taxable_base_reference": round(fed_taxable_ann, 2),
        "brokeragelink_balance": float(_bl_live["balance"]),
        "brokeragelink_source": _bl_live.get("source"),
        "brokeragelink_as_of": _bl_live.get("as_of"),
        "brokeragelink_tax_character": _bl_live.get("tax_character")
        or "pre-tax traditional 401k (BrokerageLink)",
        "method": (
            "AGI_proxy = alex annualized_gross_base + secondary_flat_annual "
            "- pretax_401k_annualized (ytd×26/pays); "
            "taxable_proxy = max(0, AGI_proxy − std_deduction_2026 MFJ)"
        ),
        "method_notes": [
            "Other employee pretax (HSA/medical/dental/vision) not subtracted — "
            "AGI_proxy slightly high vs true AGI.",
            "Jordan flat $18k operating model; prior Sch C profit not double-counted.",
            "No credits (CTC etc.) in tax dollars shown — conversion cost is pre-credit.",
            "FL state income tax $0.",
        ],
        "as_of": prof.get("as_of"),
        "profile": prof,
    }


def _default_convert_amounts(base_taxable: float, profile: Optional[dict[str, Any]]) -> list[tuple[str, float]]:
    """Named conversion amounts including fill_bracket, jump_one_bracket, and full 401k."""
    info = marginal_bracket_info(base_taxable, profile)
    room = info.get("room_to_next")
    fill = float(room) if room is not None else 0.0

    # jump_one_bracket: dollars to reach the END of the NEXT bracket
    jump = fill
    nxt = _next_bracket_after(float(info["rate"]), profile)
    if nxt is not None:
        nxt_max = nxt.get("max")
        if nxt_max is not None:
            jump = max(0.0, float(nxt_max) - float(base_taxable))
        else:
            jump = fill

    full_401k = float(live_401k_pre_tax_balance(profile)["balance"] or 0.0)

    named: list[tuple[str, float]] = [
        ("0", 0.0),
        ("10000", 10_000.0),
        ("25000", 25_000.0),
        ("50000", 50_000.0),
        ("fill_bracket", round(fill, 2)),
        ("100000", 100_000.0),
        ("jump_one_bracket", round(jump, 2)),
    ]
    if full_401k > 0:
        named.append(("full_401k_balance", round(full_401k, 2)))
    return named


def conversion_scenarios(
    convert_amounts: Optional[list[float] | list[tuple[str, float]]] = None,
    base_taxable: Optional[float] = None,
    profile: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Roth conversion scenario rows vs a taxable baseline.

    Each row:
      convert, label, new_taxable, bracket_before, bracket_after,
      extra_tax, tax_per_roth_dollar, room_left
    """
    prof = profile if profile is not None else load_tax_profile()
    if base_taxable is None:
        base_taxable = float(build_base_taxable_2026(prof)["taxable_proxy"])
    base = max(0.0, float(base_taxable))
    base_tax = compute_tax(base, prof)
    before = marginal_bracket_info(base, prof)

    if convert_amounts is None:
        pairs = _default_convert_amounts(base, prof)
    else:
        pairs = []
        for item in convert_amounts:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                pairs.append((str(item[0]), float(item[1])))
            else:
                pairs.append((str(item), float(item)))

    rows: list[dict[str, Any]] = []
    for label, amt in pairs:
        convert = max(0.0, float(amt))
        new_taxable = base + convert
        after_tax = compute_tax(new_taxable, prof)
        extra = round(after_tax - base_tax, 2)
        per_dollar = (extra / convert) if convert > 0 else 0.0
        after = marginal_bracket_info(new_taxable, prof)
        room_left = after.get("room_to_next")
        rows.append(
            {
                "label": label,
                "convert": round(convert, 2),
                "new_taxable": round(new_taxable, 2),
                "bracket_before": before["label"],
                "bracket_after": after["label"],
                "rate_before": before["rate"],
                "rate_after": after["rate"],
                "extra_tax": extra,
                "tax_per_roth_dollar": round(per_dollar, 6),
                "room_left": None if room_left is None else round(float(room_left), 2),
                "base_tax": base_tax,
                "new_tax": after_tax,
            }
        )
    return rows


def path_summaries(base: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Three clearly separated paths for the Retirement Tax layer UI."""
    b = base if base is not None else build_base_taxable_2026()
    room = (b.get("marginal") or {}).get("room_to_next")
    room_txt = (
        f"~${room:,.0f} room left in {(b.get('marginal') or {}).get('label', '22%')}"
        if room is not None
        else "top bracket"
    )
    mega = (b.get("profile") or {}).get("mega_backdoor_plan_features") or {}
    plan_feats = load_plan_features()
    card = plan_feats.get("card_copy") or {}
    mega_status = card.get("mega_status") or mega.get("status") or "Yes"
    path_c_blurb = card.get("path_c_blurb") or (
        "Grow future paycheck dollars as Roth. Not the same as converting "
        "today’s BrokerageLink balance."
    )

    return [
        {
            "id": "A",
            "title": "Path A — Leave as-is",
            "subtitle": "No Roth move this year",
            "blurb": (
                "Leave BrokerageLink pre-tax this year — finish the second mortgage "
                "before paying tax to convert."
            ),
            "emphasis": "default",
        },
        {
            "id": "B",
            "title": "Path B — Move some to Roth",
            "subtitle": f"See extra tax · {room_txt}",
            "blurb": (
                "Optionally move some pre-tax 401k (workplace retirement) into Roth "
                "and see the extra federal tax this year."
            ),
            "emphasis": "scenario",
        },
        {
            "id": "C",
            "title": "Path C — Mega backdoor",
            "subtitle": card.get("path_c_headline") or "Mega backdoor: AVAILABLE",
            "blurb": path_c_blurb,
            "emphasis": "available",
            "mega_status": mega_status,
        },
    ]


def worth_it_verdict(base: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """One-line verdict + ≤3 bullets. Leans NOT YET while Home equity is open
    and/or conversions push 22% → 24% for modest benefit.
    """
    b = base if base is not None else build_base_taxable_2026()
    margin = b.get("marginal") or {}
    rate = float(margin.get("rate") or 0)
    room = margin.get("room_to_next")
    bl_note = b.get("brokeragelink_tax_character") or "pre-tax traditional 401k"

    # Small conversion that still stays in bracket vs one that jumps.
    scenarios = conversion_scenarios(base_taxable=float(b["taxable_proxy"]), profile=b.get("profile"))
    fill_row = next((r for r in scenarios if r["label"] == "fill_bracket"), None)
    jump_row = next((r for r in scenarios if r["label"] == "25000"), None)

    pushes_24 = False
    if jump_row and jump_row["rate_after"] > rate + 1e-12:
        pushes_24 = True
    if room is not None and float(room) < 25_000:
        pushes_24 = True

    headline = "NOT YET — keep powder dry on Roth conversions"
    bullets = [
        "Home equity mortgage is still open (highest rate) — cash for conversion tax competes with that payoff.",
        (
            f"Base taxable ≈ ${float(b['taxable_proxy']):,.0f} sits in the "
            f"{margin.get('label', '22%')} bracket"
            + (
                f" with only ~${float(room):,.0f} of room"
                if room is not None
                else ""
            )
            + "; modest conversions quickly push 22% → 24%."
            if pushes_24 or (room is not None and float(room) < 30_000)
            else f"Marginal is {margin.get('label')} — size conversions carefully."
        ),
        f"BrokerageLink (~${float(b.get('brokeragelink_balance') or 0):,.0f}) is still {bl_note} — not Roth. Show the tax cost before converting.",
    ]
    # Trim to ≤3
    bullets = bullets[:3]

    detail = {
        "fill_bracket_convert": None if not fill_row else fill_row["convert"],
        "fill_bracket_extra_tax": None if not fill_row else fill_row["extra_tax"],
        "pushes_24_on_25k": pushes_24,
    }
    return {
        "verdict": headline,
        "headline": headline,
        "bullets": bullets,
        "lean": "not_yet",
        "detail": detail,
    }


def tax_layer_bundle(profile: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Convenience bundle for the Retirement page Tax layer section."""
    prof = profile if profile is not None else load_tax_profile()
    base = build_base_taxable_2026(prof)
    scenarios = conversion_scenarios(
        base_taxable=float(base["taxable_proxy"]),
        profile=prof,
    )
    return {
        "base": base,
        "scenarios": scenarios,
        "paths": path_summaries(base),
        "verdict": worth_it_verdict(base),
        "history": load_tax_history(),
    }
