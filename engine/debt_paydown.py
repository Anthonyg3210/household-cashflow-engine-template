"""Debt paydown amortization + persistence (demo mortgages + EduServe student loans).

Cash-flow twin Savings −$3500/mo is the second mortgage's extra principal — analytics only;
do not change start_balance or double-count in the projection engine. After the second,
what-ifs may redirect that extra to student loans (higher rate) or the first mortgage
(extra_start_month). Cash twin already budgets Student Loans −$650.00/mo — do not double-count.
"""
from __future__ import annotations

import json
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
DEBTS_PATH = _ROOT / "data" / "debts.json"

# Excel-track checkpoints (demo workbook sheet) for optional validation caption.
# Model uses proper amortization; small drifts vs sheet quirks are expected.
DEFAULT_EXCEL_CHECKPOINTS = {
    "2026-09": 70000.0,
    "2026-10": 68000.0,
    "2026-11": 66000.0,
    "2026-12": 64000.0,
    "2027-01": 62000.0,
    "2027-02": 60000.0,
    "2027-03": 58000.0,
}


@dataclass
class AmortRow:
    """One month of amortization."""

    month: str  # YYYY-MM
    opening_balance: float
    interest: float
    principal_regular: float
    principal_extra: float
    principal_lump: float
    total_principal: float
    payment_total: float
    closing_balance: float
    is_payoff: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AmortSchedule:
    rows: list[AmortRow] = field(default_factory=list)
    payoff_month: Optional[str] = None
    payoff_date: Optional[date] = None
    total_interest: float = 0.0
    total_principal_regular: float = 0.0
    total_principal_extra: float = 0.0
    total_principal_lump: float = 0.0
    months_to_payoff: int = 0  # payment months until zero (excl. opening snapshot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "payoff_month": self.payoff_month,
            "payoff_date": self.payoff_date.isoformat() if self.payoff_date else None,
            "total_interest": self.total_interest,
            "total_principal_regular": self.total_principal_regular,
            "total_principal_extra": self.total_principal_extra,
            "total_principal_lump": self.total_principal_lump,
            "months_to_payoff": self.months_to_payoff,
        }


def debts_path() -> Path:
    return DEBTS_PATH


def _empty_store() -> dict[str, Any]:
    return {
        "as_of": None,
        "cashflow_link_note": (
            "Cash-flow twin Savings −$2,000/mo is this second-mortgage extra principal. "
            "This page is debt analytics only — do not double-count in the cash engine; "
            "start_balance unchanged."
        ),
        "default_scenario": {
            "label": "example bonus",
            "note": "Example bonus payment for what-if only — not a balance owed.",
            "lump_sum": 24000.0,
            "lump_date": "2027-01-01",
        },
        "debts": [],
    }


def default_seed() -> dict[str, Any]:
    """Canonical Sep-2026 seed from lender screenshots / Excel track."""
    return {
        "as_of": "2026-09-10",
        "cashflow_link_note": (
            "Cash-flow twin Savings −$2,000/mo is this second-mortgage extra principal. "
            "This page is debt analytics only — do not double-count in the cash engine; "
            "start_balance unchanged."
        ),
        "default_scenario": {
            "label": "example bonus",
            "note": "Example bonus payment for what-if only — not a balance owed.",
            "lump_sum": 24000.0,
            "lump_date": "2027-01-01",
        },
        "debts": [
            {
                "id": "mortgage_second",
                "name": "Home equity (demo)",
                "kind": "second_mortgage",
                "status": "active",
                "property": "100 Demo Lane, Springfield, ST 00000",
                "borrower": "ALEX RIVERA",
                "loan_number": "DEMO-MTG-2001",
                "annual_rate": 0.07900,
                "original_balance": 125000.0,
                "current_balance": 72000.00,
                "balance_as_of": "2026-09-10",
                "balance_note": (
                    "After regular Sep payment posted (~2026-09-10). "
                    "Sep extra $2,000 applied as first projection step → Excel Sep ~~$70,000."
                ),
                "regular_payment": 950.00,
                "escrow": 0.0,
                "extra_principal_monthly": 2000.0,
                "payment_day": 11,
                "projection": {
                    "mode": "extra_only_first_month",
                    "first_month": "2026-09",
                },
                "excel_checkpoints": dict(DEFAULT_EXCEL_CHECKPOINTS),
                "goal_narrative": (
                    "Continue $2,000 extra through end of 2027 → paid off ~ end Dec 2027 / Jan 1 2028."
                ),
            },
            {
                "id": "mortgage_first",
                "name": "Primary mortgage (demo)",
                "kind": "first_mortgage",
                "status": "active",
                "property": "100 Demo Lane, Springfield, ST 00000",
                "borrower": "ALEX RIVERA",
                "loan_number": None,
                "annual_rate": 0.03500,
                "original_balance": 360000.0,
                "current_balance": 265000.00,
                "balance_as_of": "2026-09-11",
                "balance_note": (
                    "After regular Sep payment posted (~2026-09-11). "
                    "Escrow is informational only — not amortized as principal."
                ),
                "regular_payment": 1800.00,
                "escrow": 650.00,
                "escrow_balance": 7200.00,
                "total_payment": 2450.00,
                "last_payment_split": {
                    "principal": 1200.00,
                    "interest": 550.00,
                    "escrow": 650.00,
                    "date": "2026-09-11",
                },
                "extra_principal_monthly": 0.0,
                "extra_start_month": "2028-01",
                "closing_date": "2020-09-22",
                "maturity_date": "2040-10-01",
                "next_payment_date": "2026-10-01",
                "payment_day": 1,
                "projection": {
                    "mode": "full",
                    "first_month": "2026-10",
                },
                "goal_narrative": (
                    "Lowest rate 2.875% — keep minimum P&I for now while the second is the focus. "
                    "After the second (~end 2027), student loans (5.375%) usually win on interest "
                    "math before pointing the $2,000/mo Savings extra here (what-if starts 2028-01)."
                ),
            },
            {
                "id": "student_loans",
                "name": "EduServe student loans",
                "kind": "student_loans",
                "status": "active",
                "servicer": "EduServe",
                "account_number": "DEMO-EDU-4402",
                "repayment_plan": "Standard Repayment",
                "borrower": "ALEX RIVERA",
                "annual_rate": 0.05500,
                "regulatory_rate": 0.06500,
                "original_balance": None,
                "current_balance": 98000.00,
                "principal_balance": 97900.00,
                "unpaid_interest": 100.00,
                "balance_as_of": "2026-09-11",
                "balance_note": (
                    "EduServe screenshots ~2026-09-11. Total $103,855.28 = principal "
                    "$103,763.66 + unpaid interest $100.00. Last payment $650.00 on 2026-09-06. "
                    "Cash twin already has Student Loans −$650.00/mo — do not double-count."
                ),
                "regular_payment": 650.00,
                "last_payment": {"amount": 650.00, "date": "2026-09-06"},
                "extra_principal_monthly": 0.0,
                "extra_start_month": "2028-01",
                "payment_day": 6,
                "projection": {"mode": "full", "first_month": "2026-10"},
                "groups": [
                    {
                        "id": "AM",
                        "name": "Group AM — DIRECT CONSOL",
                        "outstanding": 25000.00,
                        "principal": 24950.00,
                        "unpaid_interest": 23.01,
                        "effective_rate": 0.05500,
                        "regulatory_rate": 0.06500,
                        "payment": 160.00,
                        "daily_accrual": 3.83,
                    },
                    {
                        "id": "AN",
                        "name": "Group AN — DIRECT CONSOL",
                        "outstanding": 73000.00,
                        "principal": 72950.00,
                        "unpaid_interest": 68.61,
                        "effective_rate": 0.05500,
                        "regulatory_rate": 0.06500,
                        "payment": 490.00,
                        "daily_accrual": 11.44,
                    },
                ],
                "goal_narrative": (
                    "Keep the $650.00/mo minimum for now while the second mortgage is the focus. "
                    "After the second is paid (~end 2027), the $2,000/mo Savings extra can redirect "
                    "here (default what-if starts 2028-01). Student rate 5.375% is higher than the "
                    "first mortgage 2.875%, so after the second, extra here usually beats the first "
                    "on interest math."
                ),
            },
        ],
    }


def load_debts(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or DEBTS_PATH
    if not p.exists():
        seed = default_seed()
        save_debts(seed, path=p)
        return seed
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_seed()
    if not isinstance(raw, dict) or "debts" not in raw:
        return default_seed()
    return raw


def save_debts(store: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    p = path or DEBTS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return load_debts(p)


def get_debt(store: dict[str, Any], debt_id: str) -> Optional[dict[str, Any]]:
    for d in store.get("debts") or []:
        if d.get("id") == debt_id:
            return d
    return None


def update_debt_balance(
    debt_id: str,
    *,
    current_balance: Optional[float],
    balance_as_of: Optional[str] = None,
    extra_principal_monthly: Optional[float] = None,
    regular_payment: Optional[float] = None,
    annual_rate: Optional[float] = None,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """Refresh a debt's balance / payment fields from screenshots or CSV later."""
    store = load_debts(path)
    found = False
    for d in store.get("debts") or []:
        if d.get("id") != debt_id:
            continue
        found = True
        if current_balance is not None:
            d["current_balance"] = float(current_balance)
            d["status"] = "active"
        if balance_as_of is not None:
            d["balance_as_of"] = balance_as_of
        if extra_principal_monthly is not None:
            d["extra_principal_monthly"] = float(extra_principal_monthly)
        if regular_payment is not None:
            d["regular_payment"] = float(regular_payment)
        if annual_rate is not None:
            d["annual_rate"] = float(annual_rate)
        break
    if not found:
        raise KeyError(f"Unknown debt id: {debt_id}")
    if balance_as_of:
        store["as_of"] = balance_as_of
    return save_debts(store, path=path)


def _parse_ym(ym: str) -> tuple[int, int]:
    y, m = ym.split("-")
    return int(y), int(m)


def _fmt_ym(y: int, m: int) -> str:
    return f"{y}-{m:02d}"


def add_months(y: int, m: int, n: int = 1) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + n
    return idx // 12, idx % 12 + 1


def payoff_date_for_month(ym: str, payment_day: int = 11) -> date:
    y, m = _parse_ym(ym)
    last = monthrange(y, m)[1]
    day = min(max(1, payment_day), last)
    return date(y, m, day)


def monthly_rate(annual_rate: float) -> float:
    return float(annual_rate) / 12.0


def parse_lump_date(value: Any) -> Optional[str]:
    """Return YYYY-MM from date / str for lump-sum month matching."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return f"{value.year}-{value.month:02d}"
    s = str(value).strip()
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return None



def normalize_lumps(
    *,
    lump_sum: float = 0.0,
    lump_month: Optional[str] = None,
    lumps: Optional[list] = None,
) -> dict[str, float]:
    """Merge legacy single lump + list of bonuses into {YYYY-MM: amount}.

    Each list item may be ``{"amount": float, "month"|"date": ...}`` or
    ``(amount, month_or_date)``. Same-month amounts are summed.
    """
    out: dict[str, float] = {}
    for item in lumps or []:
        amt = 0.0
        ym = None
        if isinstance(item, dict):
            amt = float(item.get("amount") or 0.0)
            ym = parse_lump_date(item.get("month") or item.get("date"))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            amt = float(item[0] or 0.0)
            ym = parse_lump_date(item[1])
        if ym and amt > 0:
            out[ym] = round(out.get(ym, 0.0) + amt, 2)
    if lump_month and float(lump_sum or 0.0) > 0:
        ym = parse_lump_date(lump_month)
        if ym:
            out[ym] = round(out.get(ym, 0.0) + float(lump_sum), 2)
    return out


def amortize(
    balance: float,
    annual_rate: float,
    regular_payment: float,
    extra_principal: float = 0.0,
    *,
    first_month: str,
    mode: str = "extra_only_first_month",
    lump_sum: float = 0.0,
    lump_month: Optional[str] = None,
    lumps: Optional[list] = None,
    payment_day: int = 11,
    max_months: int = 480,
    round_cents: bool = True,
    extra_start_month: Optional[str] = None,
) -> AmortSchedule:
    """Amortize a loan with scheduled payment + optional extra principal + bonus lumps.

    mode:
      - ``extra_only_first_month``: first_month applies only extra (regular already posted).
      - ``full``: every month including first accrues interest and takes regular+extra.

    Each full month: interest on opening balance, then apply regular (interest first),
    then lump(s) for that month, then extra principal. Tracks principal from minimum vs extra.

    ``lumps`` is a list of ``{amount, month|date}`` (or ``(amount, month)``); legacy
    ``lump_sum`` + ``lump_month`` still work and merge into the same map (supports 1–2+ bonuses).

    ``extra_start_month`` (YYYY-MM): if set, monthly extra principal applies only in that
    month and later (e.g. first-mortgage what-if after second payoff ~2028-01).
    """
    if balance is None or balance <= 0:
        return AmortSchedule(payoff_month=None, payoff_date=None, months_to_payoff=0)

    bal = float(balance)
    r_pay = float(regular_payment)
    extra_cap = max(0.0, float(extra_principal or 0.0))
    extra_from = parse_lump_date(extra_start_month)  # YYYY-MM or None
    lump_by_month = normalize_lumps(
        lump_sum=lump_sum, lump_month=lump_month, lumps=lumps
    )
    mrate = monthly_rate(annual_rate)
    y, m = _parse_ym(first_month)

    sched = AmortSchedule()
    payment_months = 0

    def _r(x: float) -> float:
        return round(x, 2) if round_cents else x

    for step in range(max_months + 1):
        ym = _fmt_ym(y, m)
        opening = _r(bal)
        interest = 0.0
        prin_reg = 0.0
        prin_extra = 0.0
        prin_lump = 0.0

        is_first = step == 0
        apply_full = not (is_first and mode == "extra_only_first_month")
        # Deferred extra: $0 until extra_start_month (inclusive)
        if extra_from and ym < extra_from:
            extra = 0.0
        else:
            extra = extra_cap

        if apply_full:
            interest = _r(bal * mrate)
            due = bal + interest
            # Lump applied with this month's payment (after interest accrual).
            month_lump = float(lump_by_month.get(ym) or 0.0)

            if r_pay + extra + month_lump >= due - 1e-9:
                # Final month — pay interest + remaining principal; trim extra/lump.
                prin_reg = min(bal, max(0.0, min(r_pay - interest, bal))) if r_pay > interest else 0.0
                # Prefer allocating: regular toward interest+prin, then lump, then extra
                remaining = bal
                # Interest is paid as part of payment_total but does not reduce principal
                avail_reg_prin = max(0.0, r_pay - interest)
                prin_reg = min(remaining, avail_reg_prin)
                remaining = _r(remaining - prin_reg)
                prin_lump = min(remaining, month_lump)
                remaining = _r(remaining - prin_lump)
                prin_extra = min(remaining, extra)
                remaining = _r(remaining - prin_extra)
                # If still residual (payment short of interest edge case), clear with lump/extra already maxed
                if remaining > 0.005:
                    # Fold residual into principal_regular for reporting
                    prin_reg = _r(prin_reg + remaining)
                    remaining = 0.0
                bal = 0.0
                payment_months += 1
                total_prin = _r(prin_reg + prin_extra + prin_lump)
                row = AmortRow(
                    month=ym,
                    opening_balance=opening,
                    interest=interest,
                    principal_regular=_r(prin_reg),
                    principal_extra=_r(prin_extra),
                    principal_lump=_r(prin_lump),
                    total_principal=total_prin,
                    payment_total=_r(interest + total_prin),
                    closing_balance=0.0,
                    is_payoff=True,
                )
                sched.rows.append(row)
                sched.total_interest = _r(sched.total_interest + interest)
                sched.total_principal_regular = _r(sched.total_principal_regular + prin_reg)
                sched.total_principal_extra = _r(sched.total_principal_extra + prin_extra)
                sched.total_principal_lump = _r(sched.total_principal_lump + prin_lump)
                sched.payoff_month = ym
                sched.payoff_date = payoff_date_for_month(ym, payment_day)
                sched.months_to_payoff = payment_months
                return sched

            prin_reg = _r(r_pay - interest)
            bal = _r(bal - prin_reg)
            prin_lump = _r(min(month_lump, bal))
            bal = _r(bal - prin_lump)
            prin_extra = _r(min(extra, bal))
            bal = _r(bal - prin_extra)
            payment_months += 1
        else:
            # Extra-only first month (regular already posted).
            month_lump = float(lump_by_month.get(ym) or 0.0)
            prin_lump = _r(min(month_lump, bal))
            bal = _r(bal - prin_lump)
            prin_extra = _r(min(extra, bal))
            bal = _r(bal - prin_extra)
            # Count as a calendar month on the schedule but not a "payment month" for
            # months_to_payoff? User cares about payoff date; include in row list.
            # months_to_payoff counts months until zero from projection start including
            # this step if it pays off (unlikely).
            if bal <= 0.005:
                bal = 0.0
                payment_months += 1
                total_prin = _r(prin_reg + prin_extra + prin_lump)
                row = AmortRow(
                    month=ym,
                    opening_balance=opening,
                    interest=0.0,
                    principal_regular=0.0,
                    principal_extra=_r(prin_extra),
                    principal_lump=_r(prin_lump),
                    total_principal=total_prin,
                    payment_total=total_prin,
                    closing_balance=0.0,
                    is_payoff=True,
                )
                sched.rows.append(row)
                sched.total_principal_extra = _r(sched.total_principal_extra + prin_extra)
                sched.total_principal_lump = _r(sched.total_principal_lump + prin_lump)
                sched.payoff_month = ym
                sched.payoff_date = payoff_date_for_month(ym, payment_day)
                sched.months_to_payoff = payment_months
                return sched

        if bal < 0:
            bal = 0.0
        total_prin = _r(prin_reg + prin_extra + prin_lump)
        is_payoff = bal <= 0.005
        if is_payoff:
            bal = 0.0
        row = AmortRow(
            month=ym,
            opening_balance=opening,
            interest=interest,
            principal_regular=_r(prin_reg),
            principal_extra=_r(prin_extra),
            principal_lump=_r(prin_lump),
            total_principal=total_prin,
            payment_total=_r(interest + total_prin),
            closing_balance=_r(bal),
            is_payoff=is_payoff,
        )
        sched.rows.append(row)
        sched.total_interest = _r(sched.total_interest + interest)
        sched.total_principal_regular = _r(sched.total_principal_regular + prin_reg)
        sched.total_principal_extra = _r(sched.total_principal_extra + prin_extra)
        sched.total_principal_lump = _r(sched.total_principal_lump + prin_lump)

        if is_payoff:
            sched.payoff_month = ym
            sched.payoff_date = payoff_date_for_month(ym, payment_day)
            sched.months_to_payoff = payment_months
            return sched

        y, m = add_months(y, m, 1)

    sched.months_to_payoff = payment_months
    return sched


def schedule_for_debt(
    debt: dict[str, Any],
    *,
    extra_principal: Optional[float] = None,
    lump_sum: float = 0.0,
    lump_month: Optional[str] = None,
    lumps: Optional[list] = None,
    extra_start_month: Optional[str] = None,
) -> AmortSchedule:
    """Build schedule from a debts.json debt record.

    Pass ``lumps=[{amount, month}, ...]`` for one or two (or more) bonus payments;
    legacy ``lump_sum`` + ``lump_month`` still work.

    ``extra_start_month`` overrides ``debt["extra_start_month"]`` when provided
    (use for first-mortgage what-ifs that start after the second is paid).
    """
    bal = debt.get("current_balance")
    if bal is None:
        return AmortSchedule()
    rate = float(debt.get("annual_rate") or 0.0)
    payment = float(debt.get("regular_payment") or 0.0)
    extra = (
        float(extra_principal)
        if extra_principal is not None
        else float(debt.get("extra_principal_monthly") or 0.0)
    )
    proj = debt.get("projection") or {}
    mode = proj.get("mode") or "full"
    first_month = proj.get("first_month")
    if not first_month:
        as_of = debt.get("balance_as_of") or "2026-09-01"
        first_month = as_of[:7]
    payment_day = int(debt.get("payment_day") or 11)
    # None → debt default; "" / falsy string → no deferral (extra from first month).
    if extra_start_month is None:
        extra_from = debt.get("extra_start_month")
    else:
        extra_from = extra_start_month  # may be "" to clear deferral
    return amortize(
        float(bal),
        rate,
        payment,
        extra,
        first_month=first_month,
        mode=mode,
        lump_sum=lump_sum,
        lump_month=lump_month,
        lumps=lumps,
        payment_day=payment_day,
        extra_start_month=parse_lump_date(extra_from) if extra_from else None,
    )


def compare_schedules(
    baseline: AmortSchedule,
    scenario: AmortSchedule,
) -> dict[str, Any]:
    """Months saved / interest saved vs baseline."""
    b_months = baseline.months_to_payoff
    s_months = scenario.months_to_payoff
    months_saved = None
    if baseline.payoff_month and scenario.payoff_month:
        by, bm = _parse_ym(baseline.payoff_month)
        sy, sm = _parse_ym(scenario.payoff_month)
        months_saved = (by * 12 + bm) - (sy * 12 + sm)
    elif b_months and s_months:
        months_saved = b_months - s_months
    interest_saved = round(baseline.total_interest - scenario.total_interest, 2)
    return {
        "baseline_payoff_month": baseline.payoff_month,
        "baseline_payoff_date": baseline.payoff_date.isoformat() if baseline.payoff_date else None,
        "baseline_total_interest": baseline.total_interest,
        "baseline_months": b_months,
        "scenario_payoff_month": scenario.payoff_month,
        "scenario_payoff_date": scenario.payoff_date.isoformat() if scenario.payoff_date else None,
        "scenario_total_interest": scenario.total_interest,
        "scenario_months": s_months,
        "months_saved": months_saved,
        "interest_saved": interest_saved,
    }


def excel_checkpoint_caption(
    schedule: AmortSchedule,
    checkpoints: Optional[dict[str, float]] = None,
    *,
    tol: float = 1.0,
) -> str:
    """Short validation caption vs demo workbook Sep–Mar track."""
    cps = checkpoints or DEFAULT_EXCEL_CHECKPOINTS
    by_month = {r.month: r.closing_balance for r in schedule.rows}
    parts = []
    max_abs = 0.0
    for ym, excel_bal in cps.items():
        model = by_month.get(ym)
        if model is None:
            continue
        diff = model - float(excel_bal)
        max_abs = max(max_abs, abs(diff))
        parts.append(f"{ym}: model ${model:,.2f} vs Excel ${float(excel_bal):,.2f} (Δ ${diff:+.2f})")
    if not parts:
        return "No overlapping Excel checkpoints to compare."
    status = (
        "matches your Excel sheet within ~$1"
        if max_abs <= tol
        else f"max difference ${max_abs:.2f} (sheet quirks OK)"
    )
    return "Excel cross-check (" + status + "): " + "; ".join(parts)


def balance_series(schedule: AmortSchedule) -> list[dict[str, Any]]:
    """Chart-friendly closing balances (include opening snapshot before first row)."""
    out = []
    for r in schedule.rows:
        out.append(
            {
                "month": r.month,
                "balance": r.closing_balance,
                "interest": r.interest,
                "principal_regular": r.principal_regular,
                "principal_extra": r.principal_extra,
                "principal_lump": r.principal_lump,
            }
        )
    return out
