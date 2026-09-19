"""Retirement runway — age-aware SWR nest eggs, lifestyle levels, snapshot I/O.

Permanent Retirement OS rules:
- Age-aware rigid SWR midpoints (never one nest egg for all ages):
  50 → 3.4% (≈29.4×), 55 → 3.6% (≈27.8×), 60 → 3.9% (≈25.6×).
- Three lifestyle levels: Floor / Comfort / Life (Comfort default until
  transactions.csv learns a real observed spend).
- Classic 25× Comfort is a footnote only.
- Flex comfort = need / (SWR + 0.6 pts) as secondary italic/footnote.
- BrokerageLink is a retirement asset for this module only; it must not feed
  the Dashboard / Bills Brokerage pictorial card (that stays Individual /
  net_worth).
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

_ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = _ROOT / "data" / "retirement_plan.json"
ACCOUNTS_PATH = _ROOT / "data" / "retirement_accounts_private.json"
SNAPSHOT_PATH = _ROOT / "data" / "retirement_snapshot.json"
HISTORY_PATH = _ROOT / "data" / "retirement_history.jsonl"
TRANSACTIONS_PATH = _ROOT / "data" / "transactions.csv"

# Categories that are aggressive debt payoff (not ongoing lifestyle once debts die).
DEFAULT_DEBT_EXTRA_CATEGORIES = ("Savings",)

# High-interest / temporary debts assumed gone by early retirement (toggleable).
DEFAULT_HIGH_INTEREST_DEBT_CATEGORIES = ("Student Loans",)

# Age-aware rigid SWR midpoints (Retirement OS permanent).
AGE_AWARE_SWR: dict[int, float] = {
    50: 0.034,  # ≈29.4×
    55: 0.036,  # ≈27.8×
    60: 0.039,  # ≈25.6×
}

# Multipliers for display/docs (1 / SWR).
AGE_AWARE_MULTIPLIER: dict[int, float] = {
    age: (1.0 / rate) for age, rate in AGE_AWARE_SWR.items()
}

FLEX_SWR_BOOST = 0.006  # +0.6 percentage points for flex comfort
CLASSIC_SWR = 0.04  # 25× footnote only
DEFAULT_REAL_RETURN = 0.05  # ~7% nominal − 2% inflation
DEFAULT_AGES = (50, 55, 60)

# Temporary twin lifestyle until transactions.csv learns observed spend.
DEFAULT_COMFORT_ANNUAL = 103_023.61
DEFAULT_STATED_MONTHLY = 8_585.30
FLOOR_RATIO = 0.80  # Floor = 80% of Comfort
LIFE_RATIO = 1.20  # Life = 120% of Comfort
HEALTHCARE_TEMP_ADDER_ANNUAL = 24_000.0  # couple pre-65 temporary adder

# Legacy radio labels (UI may still reference; OS prefers age-aware).
WITHDRAWAL_PRESETS = {
    "4%": 0.04,
    "3.5%": 0.035,
}

DEFAULT_COURSE_SUGGESTIONS = [
    "Primary mortgage — finish the second mortgage (highest rate) before accelerating 401k extras.",
    "Build the taxable bridge (Fidelity Individual) before age 50 so early years aren't forced BrokerageLink withdrawals.",
    "Capture freed cash when Home equity / student loans die — route extras into the retirement engine, don't let lifestyle expand.",
    "Rebuild Comfort / Floor / Life from transactions.csv once the warehouse has real spend (T12 median beats temporary twin).",
    "Don't raid BrokerageLink for lifestyle spending — that's the core retirement engine.",
    "Social Security is not counted here until 62+; plan early years as portfolio-only.",
    "SPCX is AXS SPAC and New Issue ETF — NOT SpaceX common stock. Concentration risk is real even if the thesis is intentional.",
]


def plan_path() -> Path:
    return PLAN_PATH


def accounts_path() -> Path:
    return ACCOUNTS_PATH


def snapshot_path() -> Path:
    return SNAPSHOT_PATH


def history_path() -> Path:
    return HISTORY_PATH


def swr_for_age(retire_age: int) -> float:
    """Rigid age-aware SWR midpoint. Raises if age not in the OS table."""
    age = int(retire_age)
    if age not in AGE_AWARE_SWR:
        raise ValueError(
            f"No age-aware SWR for retire_age={age}; "
            f"supported ages: {sorted(AGE_AWARE_SWR)}"
        )
    return AGE_AWARE_SWR[age]


def nest_egg_for_age(annual_need: float, retire_age: int) -> float:
    """Age-aware rigid nest egg = annual need / SWR(age)."""
    return nest_egg_target(annual_need, swr_for_age(retire_age))


def flex_nest_egg(annual_need: float, retire_age: int, boost: float = FLEX_SWR_BOOST) -> float:
    """Secondary flex comfort: need / (SWR + boost pts)."""
    rate = swr_for_age(retire_age) + float(boost)
    return nest_egg_target(annual_need, rate)


def classic_25x(annual_need: float) -> float:
    """Classic 25× Comfort — footnote only, not the primary target."""
    return nest_egg_target(annual_need, CLASSIC_SWR)


def default_plan() -> dict[str, Any]:
    """Seed plan for Alex Rivera (age 40 as of 2026-09)."""
    return {
        "as_of": "2026-09-14",
        "person": {
            "name": "Alex Rivera",
            "birth_year": 1986,
            "age_years": 40,
            "age_as_of": "2026-09",
            "role_note": "Northstar Tech senior manager",
        },
        "income_context": {
            "alex_biweekly": 4200.00,
            "alex_annual_approx": 117123.76,
            "jordan_monthly_operating": 1500.0,
            "jordan_note": (
                "Jordan ~$1,500/mo + side_gig fading; "
                "goal = same lifestyle income in retirement"
            ),
        },
        "assumptions": {
            "withdrawal_rate": 0.04,  # classic footnote only
            "real_return": DEFAULT_REAL_RETURN,
            "nominal_return": 0.07,
            "inflation": 0.02,
            "return_note": "Default ~5% real (7% nominal − 2% inflation)",
            "age_aware_swr": dict(AGE_AWARE_SWR),
            "flex_swr_boost": FLEX_SWR_BOOST,
            "exclude_debt_payoff_extras": True,
            "assume_high_interest_debt_paid": True,
            "housing_budget_mode": "keep_housing",
            "social_security_counted": False,
            "social_security_note": "Social Security not counted until age 62+",
            "healthcare_temp_adder_annual": HEALTHCARE_TEMP_ADDER_ANNUAL,
        },
        "lifestyle_need": {
            "annual_override": None,
            "comfort_annual": DEFAULT_COMFORT_ANNUAL,
            "floor_annual": round(DEFAULT_COMFORT_ANNUAL * FLOOR_RATIO, 2),
            "life_annual": round(DEFAULT_COMFORT_ANNUAL * LIFE_RATIO, 2),
            "stated_monthly": DEFAULT_STATED_MONTHLY,
            "source": "temporary_twin",
            "notes": (
                "Comfort default $103,023.61 until transactions.csv learns; "
                "Floor=80% Comfort, Life=120% Comfort."
            ),
        },
        "custom_retire_age": None,
        "allocation_buckets": [
            {"id": "spcx_spac_new_issue", "label": "SPCX (SPAC / new-issue ETF)", "pct": 97.7},
            {"id": "taxable_brokerage", "label": "Fidelity Individual (taxable)", "pct": 2.2},
            {"id": "cash_core", "label": "Cash / core (FDRXX)", "pct": 0.1},
        ],
        "allocation_placeholder": (
            "Paste 401k screenshot / update holdings — coarse buckets only for now."
        ),
        "course_suggestions": list(DEFAULT_COURSE_SUGGESTIONS),
        "concentration_note": (
            "⚠️ SPCX ≠ SpaceX stock. BrokerageLink is ~100% SPCX "
            "(AXS SPAC and New Issue ETF) — a high-conviction, high-concentration "
            "bet, NOT SpaceX common stock. Runway math uses total dollars; "
            "sequence-of-returns / single-name ETF risk is higher than a "
            "diversified equity/bond mix."
        ),
    }


def load_plan(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or PLAN_PATH
    base = default_plan()
    if not p.exists():
        return base
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(raw, dict):
        return base
    return _deep_merge(base, raw)


def save_plan(plan: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    p = path or PLAN_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(plan)
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return load_plan(p)


def load_retirement_accounts(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or ACCOUNTS_PATH
    if not p.exists():
        return {
            "as_of": None,
            "individual": {"balance": 0.0},
            "brokeragelink": {"balance": 0.0, "show_on_dashboard": False},
        }
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # Enforce BrokerageLink off Dashboard even if JSON omits the flag.
    bl = dict(raw.get("brokeragelink") or {})
    if "show_on_dashboard" not in bl:
        bl["show_on_dashboard"] = False
    raw = dict(raw)
    raw["brokeragelink"] = bl
    return raw


def save_retirement_accounts(
    accounts: dict[str, Any], path: Optional[Path] = None
) -> dict[str, Any]:
    p = path or ACCOUNTS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(accounts)
    bl = dict(payload.get("brokeragelink") or {})
    bl["show_on_dashboard"] = False  # hard rule
    payload["brokeragelink"] = bl
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return load_retirement_accounts(p)


def current_retirement_assets(accounts: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Sum assets used for retirement math (BrokerageLink + Individual + optional other).

    BrokerageLink is included here even when show_on_dashboard is False.
    """
    acc = accounts if accounts is not None else load_retirement_accounts()
    individual = float((acc.get("individual") or {}).get("balance") or 0.0)
    bl_block = acc.get("brokeragelink") or {}
    if bl_block.get("balance") is not None:
        brokeragelink = float(bl_block.get("balance") or 0.0)
    else:
        brokeragelink = float(acc.get("brokeragelink_seen_on_screenshot") or 0.0)
    other = 0.0
    other_items: list[dict[str, Any]] = []
    for item in acc.get("other_retirement_assets") or []:
        try:
            bal = float(item.get("balance") or 0.0)
        except (TypeError, ValueError):
            bal = 0.0
        other += bal
        other_items.append({"name": item.get("name") or "Other", "balance": bal})
    total = individual + brokeragelink + other
    spcx_pct = None
    positions = bl_block.get("positions") or []
    if brokeragelink > 0 and positions:
        spcx_val = 0.0
        for pos in positions:
            ticker = str(pos.get("ticker") or "").upper()
            if ticker == "SPCX":
                spcx_val += float(pos.get("value") or 0.0)
        spcx_pct = spcx_val / brokeragelink if brokeragelink else None
    return {
        "individual": individual,
        "brokeragelink": brokeragelink,
        "other": other,
        "other_items": other_items,
        "total": total,
        "as_of": acc.get("as_of") or bl_block.get("as_of"),
        "spcx_pct": spcx_pct,
        "show_brokeragelink_on_dashboard": bool(bl_block.get("show_on_dashboard") or False),
    }


def nest_egg_target(annual_lifestyle_need: float, withdrawal_rate: float = 0.04) -> float:
    """Nest egg = annual need / withdrawal rate (4% ⇒ 25×)."""
    need = float(annual_lifestyle_need)
    rate = float(withdrawal_rate)
    if need < 0:
        need = 0.0
    if rate <= 0:
        raise ValueError("withdrawal_rate must be positive")
    return need / rate


def years_until(current_age: float, retire_age: float) -> float:
    return max(0.0, float(retire_age) - float(current_age))


def project_portfolio(
    current_assets: float,
    years: float,
    real_return: float = DEFAULT_REAL_RETURN,
) -> float:
    """Grow current assets at a constant real annual return (no new contributions)."""
    assets = max(0.0, float(current_assets))
    y = max(0.0, float(years))
    r = float(real_return)
    return assets * ((1.0 + r) ** y)


def required_monthly_contribution(
    gap: float,
    years: float,
    annual_real_return: float = DEFAULT_REAL_RETURN,
) -> float:
    """Monthly contribution (end of month) to close a positive gap at real return.

    Existing assets' growth is already reflected in ``gap`` (target − projected).
    """
    g = float(gap)
    if g <= 0:
        return 0.0
    y = float(years)
    if y <= 0:
        return g  # due now — treat as lump, report as one-month figure
    n = max(1, int(round(y * 12)))
    r_ann = float(annual_real_return)
    if r_ann <= -0.999:
        return g / n
    r = r_ann / 12.0
    if abs(r) < 1e-12:
        return g / n
    return g * r / (((1.0 + r) ** n) - 1.0)


@dataclass(frozen=True)
class AgeBracketResult:
    """Legacy single-need bracket (kept for older callers/tests)."""

    retire_age: int
    years_to_go: float
    nest_egg_needed: float
    current_assets: float
    projected_assets: float
    gap: float  # positive = shortfall
    surplus: float  # positive = ahead
    monthly_contribution_to_close: float
    on_track: bool
    swr: float = 0.04


@dataclass(frozen=True)
class LifestyleAgeTile:
    """One retirement-age tile with Floor / Comfort / Life rigid nest eggs."""

    retire_age: int
    years_to_go: float
    swr_rigid: float
    floor: float
    comfort: float
    life: float
    projected_base: float
    gap_comfort: float
    extra_mo: float
    flex_comfort: float
    on_track_comfort: bool
    comfort_with_healthcare: float
    gap_comfort_with_healthcare: float
    extra_mo_with_healthcare: float


def evaluate_age_bracket(
    *,
    retire_age: int,
    current_age: float,
    annual_lifestyle_need: float,
    current_assets: float,
    withdrawal_rate: Optional[float] = None,
    real_return: float = DEFAULT_REAL_RETURN,
) -> AgeBracketResult:
    """Evaluate a single age. Uses age-aware SWR when withdrawal_rate is None."""
    years = years_until(current_age, retire_age)
    if withdrawal_rate is None and int(retire_age) in AGE_AWARE_SWR:
        rate = swr_for_age(retire_age)
    else:
        rate = float(withdrawal_rate if withdrawal_rate is not None else CLASSIC_SWR)
    target = nest_egg_target(annual_lifestyle_need, rate)
    projected = project_portfolio(current_assets, years, real_return)
    gap = target - projected
    surplus = max(0.0, -gap)
    shortfall = max(0.0, gap)
    monthly = required_monthly_contribution(shortfall, years, real_return)
    return AgeBracketResult(
        retire_age=int(retire_age),
        years_to_go=years,
        nest_egg_needed=target,
        current_assets=float(current_assets),
        projected_assets=projected,
        gap=gap,
        surplus=surplus,
        monthly_contribution_to_close=monthly,
        on_track=gap <= 0,
        swr=rate,
    )


def evaluate_brackets(
    *,
    ages: Iterable[int] = DEFAULT_AGES,
    current_age: float,
    annual_lifestyle_need: float,
    current_assets: float,
    withdrawal_rate: Optional[float] = None,
    real_return: float = DEFAULT_REAL_RETURN,
    custom_age: Optional[int] = None,
) -> list[AgeBracketResult]:
    age_list = list(ages)
    if custom_age is not None:
        ca = int(custom_age)
        if ca not in age_list and ca > 0:
            age_list.append(ca)
    return [
        evaluate_age_bracket(
            retire_age=a,
            current_age=current_age,
            annual_lifestyle_need=annual_lifestyle_need,
            current_assets=current_assets,
            withdrawal_rate=withdrawal_rate,
            real_return=real_return,
        )
        for a in age_list
    ]


def lifestyle_levels(
    comfort_annual: float,
    *,
    floor_annual: Optional[float] = None,
    life_annual: Optional[float] = None,
) -> dict[str, float]:
    comfort = float(comfort_annual)
    floor = float(floor_annual) if floor_annual is not None else comfort * FLOOR_RATIO
    life = float(life_annual) if life_annual is not None else comfort * LIFE_RATIO
    return {
        "floor_annual": floor,
        "comfort_annual": comfort,
        "life_annual": life,
        "floor_monthly": floor / 12.0,
        "comfort_monthly": comfort / 12.0,
        "life_monthly": life / 12.0,
    }


def build_age_tile(
    *,
    retire_age: int,
    current_age: float,
    floor_annual: float,
    comfort_annual: float,
    life_annual: float,
    current_assets: float,
    real_return: float = DEFAULT_REAL_RETURN,
    healthcare_adder_annual: float = 0.0,
) -> LifestyleAgeTile:
    years = years_until(current_age, retire_age)
    swr = swr_for_age(retire_age)
    floor_ne = nest_egg_target(floor_annual, swr)
    comfort_ne = nest_egg_target(comfort_annual, swr)
    life_ne = nest_egg_target(life_annual, swr)
    projected = project_portfolio(current_assets, years, real_return)
    gap = comfort_ne - projected
    extra = required_monthly_contribution(max(0.0, gap), years, real_return)
    flex = flex_nest_egg(comfort_annual, retire_age)

    comfort_hc = float(comfort_annual) + max(0.0, float(healthcare_adder_annual))
    comfort_ne_hc = nest_egg_target(comfort_hc, swr)
    gap_hc = comfort_ne_hc - projected
    extra_hc = required_monthly_contribution(max(0.0, gap_hc), years, real_return)

    return LifestyleAgeTile(
        retire_age=int(retire_age),
        years_to_go=years,
        swr_rigid=swr,
        floor=floor_ne,
        comfort=comfort_ne,
        life=life_ne,
        projected_base=projected,
        gap_comfort=gap,
        extra_mo=extra,
        flex_comfort=flex,
        on_track_comfort=gap <= 0,
        comfort_with_healthcare=comfort_ne_hc,
        gap_comfort_with_healthcare=gap_hc,
        extra_mo_with_healthcare=extra_hc,
    )


def evaluate_lifestyle_tiles(
    *,
    ages: Iterable[int] = DEFAULT_AGES,
    current_age: float,
    floor_annual: float,
    comfort_annual: float,
    life_annual: float,
    current_assets: float,
    real_return: float = DEFAULT_REAL_RETURN,
    healthcare_adder_annual: float = 0.0,
) -> list[LifestyleAgeTile]:
    return [
        build_age_tile(
            retire_age=a,
            current_age=current_age,
            floor_annual=floor_annual,
            comfort_annual=comfort_annual,
            life_annual=life_annual,
            current_assets=current_assets,
            real_return=real_return,
            healthcare_adder_annual=healthcare_adder_annual,
        )
        for a in ages
    ]


def taxable_bridge_months(
    individual_balance: float,
    comfort_annual: float,
) -> float:
    """Months of Comfort lifestyle coverable from Fidelity Individual alone."""
    monthly = float(comfort_annual) / 12.0
    if monthly <= 0:
        return 0.0
    return max(0.0, float(individual_balance) / monthly)


def transactions_row_count(path: Optional[Path] = None) -> int:
    p = path or TRANSACTIONS_PATH
    if not p.exists():
        return 0
    try:
        lines = p.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return 0
    # Header-only ⇒ 0 data rows
    return max(0, len(lines) - 1) if lines else 0


def warehouse_status(path: Optional[Path] = None) -> dict[str, Any]:
    n = transactions_row_count(path)
    if n <= 0:
        return {
            "status": "headers_created_no_transactions_yet",
            "learning_live": False,
            "row_count": 0,
            "banner": (
                "Warehouse empty — transactions.csv has headers only. "
                "Using temporary twin Comfort ($103,023.61/yr) until real spend lands."
            ),
        }
    return {
        "status": "transactions_present",
        "learning_live": True,
        "row_count": n,
        "banner": f"Warehouse live — {n} transaction row(s) available for observed spend.",
    }


def load_snapshot(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    p = path or SNAPSHOT_PATH
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def save_snapshot(snapshot: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    p = path or SNAPSHOT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(snapshot)
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def append_history(
    snapshot: dict[str, Any], path: Optional[Path] = None
) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(snapshot, separators=(",", ":"))
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def build_snapshot(
    *,
    current_age: float = 40.0,
    comfort_annual: float = DEFAULT_COMFORT_ANNUAL,
    floor_annual: Optional[float] = None,
    life_annual: Optional[float] = None,
    stated_monthly: float = DEFAULT_STATED_MONTHLY,
    current_assets: Optional[float] = None,
    individual: Optional[float] = None,
    brokeragelink: Optional[float] = None,
    real_return: float = DEFAULT_REAL_RETURN,
    healthcare_adder_annual: float = HEALTHCARE_TEMP_ADDER_ANNUAL,
    as_of: Optional[str] = None,
    accounts: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a Retirement OS snapshot dict (matches seeded schema)."""
    assets_info = current_retirement_assets(accounts)
    bl = float(brokeragelink) if brokeragelink is not None else assets_info["brokeragelink"]
    indiv = float(individual) if individual is not None else assets_info["individual"]
    total = float(current_assets) if current_assets is not None else (bl + indiv + assets_info["other"])
    levels = lifestyle_levels(
        comfort_annual, floor_annual=floor_annual, life_annual=life_annual
    )
    wh = warehouse_status()
    tiles = evaluate_lifestyle_tiles(
        current_age=current_age,
        floor_annual=levels["floor_annual"],
        comfort_annual=levels["comfort_annual"],
        life_annual=levels["life_annual"],
        current_assets=total,
        real_return=real_return,
        healthcare_adder_annual=healthcare_adder_annual,
    )
    targets: dict[str, Any] = {}
    for t in tiles:
        targets[str(t.retire_age)] = {
            "floor": round(t.floor, 2),
            "comfort": round(t.comfort, 2),
            "life": round(t.life, 2),
            "projected_base": round(t.projected_base, 2),
            "gap_comfort": round(t.gap_comfort, 2),
            "extra_mo": round(t.extra_mo, 2),
            "swr_rigid": t.swr_rigid,
            "flex_comfort": round(t.flex_comfort, 2),
            "comfort_with_healthcare": round(t.comfort_with_healthcare, 2),
            "gap_comfort_with_healthcare": round(t.gap_comfort_with_healthcare, 2),
            "extra_mo_with_healthcare": round(t.extra_mo_with_healthcare, 2),
        }
    tile_55 = next((t for t in tiles if t.retire_age == 55), tiles[0] if tiles else None)
    path_status = "unknown"
    if tile_55 is not None:
        path_status = "on_track" if tile_55.on_track_comfort else "short"

    observed_monthly = None  # filled when warehouse learns
    verdict = (
        "UNKNOWN — no transactions.csv yet; using temporary twin lifestyle"
        if not wh["learning_live"]
        else "Observed spend available — compare to stated"
    )
    bridge = taxable_bridge_months(indiv, levels["comfort_annual"])
    spcx = assets_info.get("spcx_pct")
    if spcx is None:
        spcx = 0.98  # known concentration from seed

    return {
        "as_of": as_of or today_iso(),
        "age": int(current_age),
        "warehouse_status": wh["status"],
        "learning_live": wh["learning_live"],
        "balances": {
            "brokerage_link": round(bl, 2),
            "fidelity_individual": round(indiv, 2),
            "total_retirement": round(total, 2),
            "spcx_pct": round(float(spcx), 4) if spcx is not None else None,
        },
        "spend": {
            "t12_median": observed_monthly,
            "t12_avg": None,
            "t24_median": None,
            "t6_median": None,
            "p90_month": None,
            "stated_monthly": float(stated_monthly),
            "comfort_annual": round(levels["comfort_annual"], 2),
            "floor_annual": round(levels["floor_annual"], 2),
            "life_annual": round(levels["life_annual"], 2),
            "verdict_vs_stated": verdict,
        },
        "engine_contribution_monthly_predicted": None,
        "lifestyle_fill_prior": 0.4,
        "freed_cash_hypothesis": "pending",
        "targets": targets,
        "classic_25x_comfort": round(classic_25x(levels["comfort_annual"]), 2),
        "taxable_bridge_months": round(bridge, 1),
        "healthcare_temp_adder_annual": float(healthcare_adder_annual),
        "last_primary_action": None,
        "action_result": "unknown",
        "path_status_55_comfort": path_status,
        "notes": [
            "SPCX is AXS SPAC and New Issue ETF, NOT SpaceX common stock",
            "Age-aware SWR: 50=3.4%, 55=3.6%, 60=3.9%",
            "Planning math, not licensed advice",
        ],
    }


def average_monthly_outflow(
    month_totals: Iterable[dict[str, Any]],
    *,
    exclude_categories: Optional[Iterable[str]] = None,
) -> float:
    """Average money_out from month total dicts."""
    excl = {c.strip().lower() for c in (exclude_categories or []) if c}
    vals: list[float] = []
    for row in month_totals:
        if not excl or not row.get("by_category"):
            vals.append(float(row.get("money_out") or 0.0))
            continue
        by_cat = row["by_category"]
        out = float(row.get("money_out") or 0.0)
        for name, amt in by_cat.items():
            if str(name).strip().lower() not in excl:
                continue
            a = float(amt)
            out -= abs(a)
        vals.append(max(0.0, out))
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def derive_lifestyle_need_annual(
    *,
    month_totals: Optional[Iterable[dict[str, Any]]] = None,
    exclude_debt_payoff_extras: bool = True,
    assume_high_interest_debt_paid: bool = True,
    housing_budget_mode: str = "keep_housing",
    annual_override: Optional[float] = None,
    income_based_annual: Optional[float] = None,
    debt_extra_categories: Iterable[str] = DEFAULT_DEBT_EXTRA_CATEGORIES,
    high_interest_categories: Iterable[str] = DEFAULT_HIGH_INTEREST_DEBT_CATEGORIES,
    housing_categories: Iterable[str] = ("Home Mortgage",),
    comfort_fallback: float = DEFAULT_COMFORT_ANNUAL,
) -> dict[str, Any]:
    """Derive annual lifestyle need (Comfort).

    Priority: explicit override → twin average expenses → income-based →
    temporary Comfort fallback ($103,023.61).
    """
    if annual_override is not None and float(annual_override) > 0:
        ann = float(annual_override)
        return {
            "annual": ann,
            "monthly": ann / 12.0,
            "source": "override",
            "excluded_categories": [],
        }

    excl: list[str] = []
    if exclude_debt_payoff_extras:
        excl.extend(list(debt_extra_categories))
    if assume_high_interest_debt_paid:
        excl.extend(list(high_interest_categories))
    if housing_budget_mode == "paid_off":
        excl.extend(list(housing_categories))

    if month_totals is not None:
        monthly = average_monthly_outflow(month_totals, exclude_categories=excl)
        if monthly > 0:
            return {
                "annual": monthly * 12.0,
                "monthly": monthly,
                "source": "twin_avg_expenses",
                "excluded_categories": excl,
            }

    if income_based_annual is not None and float(income_based_annual) > 0:
        ann = float(income_based_annual)
        return {
            "annual": ann,
            "monthly": ann / 12.0,
            "source": "income_replacement",
            "excluded_categories": excl,
        }

    # Temporary twin Comfort until warehouse learns
    return {
        "annual": float(comfort_fallback),
        "monthly": float(comfort_fallback) / 12.0,
        "source": "temporary_twin",
        "excluded_categories": excl,
    }


def income_replacement_annual(plan: Optional[dict[str, Any]] = None) -> float:
    p = plan if plan is not None else load_plan()
    ctx = p.get("income_context") or {}
    alex = float(ctx.get("alex_annual_approx") or 0.0)
    if alex <= 0 and ctx.get("alex_biweekly"):
        alex = float(ctx["alex_biweekly"]) * 26.0
    jordan = float(ctx.get("jordan_monthly_operating") or 0.0) * 12.0
    return alex + jordan


def build_month_totals_from_checklists(
    checklists: Iterable[Iterable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Convert bill-checklist row lists into month_totals for lifestyle derivation."""
    out: list[dict[str, Any]] = []
    for rows in checklists:
        money_out = 0.0
        by_cat: dict[str, float] = {}
        for r in rows:
            amt = float(r.get("amount") or 0.0)
            if amt >= 0:
                continue
            cat = str(r.get("category") or "Other")
            money_out += abs(amt)
            by_cat[cat] = by_cat.get(cat, 0.0) + abs(amt)
        out.append({"money_out": money_out, "by_category": by_cat})
    return out


def _deep_merge(base: dict, overlay: dict) -> dict:
    result = deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = deepcopy(v)
    return result


def course_suggestions(plan: Optional[dict[str, Any]] = None) -> list[str]:
    p = plan if plan is not None else load_plan()
    tips = p.get("course_suggestions") or DEFAULT_COURSE_SUGGESTIONS
    # Prefer OS defaults when plan still has pre-OS tips only
    return [str(t) for t in tips]


def today_iso() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Display-only formatters (no math). Safe for UI / captions / tiles.
# ---------------------------------------------------------------------------


def format_money(amount: float | None, *, empty: str = "—") -> str:
    """Full money balance: $1,234,567.89"""
    if amount is None:
        return empty
    return f"${float(amount):,.2f}"


def format_money_compact(amount: float | None, *, empty: str = "—") -> str:
    """Hero nest-egg style: $2.86M when |amount| ≥ 1M, else full money."""
    if amount is None:
        return empty
    v = float(amount)
    sign = "-" if v < 0 else ""
    av = abs(v)
    if av >= 1_000_000:
        return f"{sign}${av / 1_000_000:.2f}M"
    return f"{sign}${av:,.2f}"


def format_pct(rate: float | None, *, digits: int = 2, empty: str = "—") -> str:
    """Decimal rate → percent string: 0.034 → 3.40%"""
    if rate is None:
        return empty
    return f"{float(rate) * 100:.{int(digits)}f}%"


def format_years(years: float | None, *, empty: str = "—") -> str:
    """Years label: 15 yrs / 10.5 yrs"""
    if years is None:
        return empty
    y = float(years)
    if abs(y - round(y)) < 1e-9:
        return f"{int(round(y))} yrs"
    return f"{y:.1f} yrs"


def format_months(months: float | None, *, empty: str = "—") -> str:
    """Months label: 1.4 mo"""
    if months is None:
        return empty
    return f"{float(months):.1f} mo"
