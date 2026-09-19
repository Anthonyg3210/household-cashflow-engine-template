"""Red-month streak detection and cash-cushion math for the Dashboard.

Complements the year pitfall scorecard and mitigation cards: when consecutive
months go red (same signal as the Dashboard — days with EOD < $0), surface a
plain-English cushion so Alex/Jordan know how much to set aside before the
streak starts.
"""
from __future__ import annotations

from calendar import month_name
from math import ceil
from typing import Any, Optional


def _is_red_month(m: dict, *, key: str = "days_negative") -> bool:
    """Match Dashboard / pitfall scorecard red signal by default."""
    if key == "days_warning":
        return (m.get("days_warning") or 0) > 0
    if key == "month_end_negative":
        return float(m.get("month_end") or 0.0) < 0.0
    # Default: days_negative (EOD < $0), same as year_pitfall_scorecard
    return (m.get("days_negative") or 0) > 0 or bool(m.get("first_breach"))


def _next_ym(year: int, month: int) -> tuple[int, int]:
    if int(month) == 12:
        return int(year) + 1, 1
    return int(year), int(month) + 1


def _calendar_consecutive(a: dict, b: dict) -> bool:
    return (int(b["year"]), int(b["month"])) == _next_ym(int(a["year"]), int(a["month"]))


def cash_cushion_amount(
    months_in_streak: list[dict],
    *,
    clear_to: float = 0.0,
    balance_key: str = "min_eod",
) -> float:
    """Dollars to set aside so the deepest trough in the streak lifts to ``clear_to``.

    Uses daily ``min_eod`` by default (Dashboard red = any day EOD < $0).
    Pass ``balance_key="month_end"`` for month-end-only consistency.
    """
    if not months_in_streak:
        return 0.0
    deepest = min(float(m.get(balance_key) if m.get(balance_key) is not None else 0.0)
                  for m in months_in_streak)
    return max(0.0, float(clear_to) - deepest)


def round_up_cushion(amount: float, *, step: float = 1.0) -> float:
    """Round cushion up to the next ``step`` (default whole dollars)."""
    amt = float(amount)
    if amt <= 0:
        return 0.0
    step = float(step) if step and step > 0 else 1.0
    return float(ceil(amt / step) * step)


def _streak_payload(
    run: list[dict],
    *,
    clear_to: float = 0.0,
    balance_key: str = "min_eod",
    round_step: float = 1.0,
) -> dict[str, Any]:
    start, end = run[0], run[-1]
    deepest = min(
        float(m.get(balance_key) if m.get(balance_key) is not None else 0.0) for m in run
    )
    raw = cash_cushion_amount(run, clear_to=clear_to, balance_key=balance_key)
    rounded = round_up_cushion(raw, step=round_step)
    start_name = month_name[int(start["month"])]
    end_name = month_name[int(end["month"])]
    length = len(run)
    return {
        "start_year": int(start["year"]),
        "start_month": int(start["month"]),
        "end_year": int(end["year"]),
        "end_month": int(end["month"]),
        "start_month_name": start_name,
        "end_month_name": end_name,
        "length": length,
        "months": list(run),
        "deepest_trough": deepest,
        "cushion": raw,
        "cushion_rounded": rounded,
        "clear_to": float(clear_to),
        "plain_english": format_cushion_tip(
            start_month_name=start_name,
            end_month_name=end_name,
            length=length,
            cushion=rounded,
        ),
    }


def format_cushion_tip(
    *,
    start_month_name: str,
    end_month_name: str,
    length: int,
    cushion: float,
) -> str:
    """partner-friendly one-liner (caller escapes $ for Streamlit markdown)."""
    x = f"${float(cushion):,.0f}"
    if length <= 1:
        return (
            f"Set aside about {x} before {start_month_name} so checking "
            f"doesn't go red in {start_month_name}"
        )
    return (
        f"Set aside about {x} before {start_month_name} so checking "
        f"doesn't go red through {end_month_name}"
    )


def find_red_streaks(
    months: list[dict],
    *,
    key: str = "days_negative",
    clear_to: float = 0.0,
    balance_key: str = "min_eod",
    round_step: float = 1.0,
) -> list[dict[str, Any]]:
    """Return consecutive calendar runs of red months (sorted by start)."""
    if not months:
        return []
    ordered = sorted(months, key=lambda m: (int(m["year"]), int(m["month"])))
    streaks: list[dict[str, Any]] = []
    current: list[dict] = []
    for m in ordered:
        if _is_red_month(m, key=key):
            if current and not _calendar_consecutive(current[-1], m):
                streaks.append(
                    _streak_payload(
                        current,
                        clear_to=clear_to,
                        balance_key=balance_key,
                        round_step=round_step,
                    )
                )
                current = []
            current.append(m)
        elif current:
            streaks.append(
                _streak_payload(
                    current,
                    clear_to=clear_to,
                    balance_key=balance_key,
                    round_step=round_step,
                )
            )
            current = []
    if current:
        streaks.append(
            _streak_payload(
                current,
                clear_to=clear_to,
                balance_key=balance_key,
                round_step=round_step,
            )
        )
    return streaks


def primary_red_streak(
    months: list[dict],
    *,
    key: str = "days_negative",
    clear_to: float = 0.0,
    balance_key: str = "min_eod",
    round_step: float = 1.0,
    min_length: int = 1,
) -> Optional[dict[str, Any]]:
    """Pick the longest upcoming/visible streak; ties break to earliest start."""
    streaks = [
        s
        for s in find_red_streaks(
            months,
            key=key,
            clear_to=clear_to,
            balance_key=balance_key,
            round_step=round_step,
        )
        if int(s["length"]) >= int(min_length)
    ]
    if not streaks:
        return None
    streaks.sort(
        key=lambda s: (-int(s["length"]), int(s["start_year"]), int(s["start_month"]))
    )
    return streaks[0]
