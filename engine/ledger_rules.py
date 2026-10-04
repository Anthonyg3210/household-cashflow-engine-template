"""Generic ledger rules shared by forecast, import, and card math.

No household names, balances, or account numbers belong here.
Synthetic callers in tests are the only examples.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional


# Observed / unverified feeds must not become decision-grade forecast lines.
# Pics, statements, and bank CSV exports are not in this set.
_UNVERIFIED_EXACT = frozenset({"observed", "unverified", "plaid", "feed"})
_UNVERIFIED_PREFIXES = ("observed", "unverified", "plaid", "feed")

# Same card visit: keep one line. Higher rank wins. Never sum the stages.
_VISIT_RANK = {
    "tip_final": 40,
    "posted": 30,
    "pending": 20,
    "pre_tip": 10,
    "stale_pending": 0,
    "stale": 0,
}

_PENDING_CARD_STATUSES = frozenset({"pending", "authorization", "auth"})


def resolve_forecast_dom(
    *,
    locked_day: Optional[int] = None,
    posted_days: Optional[list[int]] = None,
    lender_next_day: Optional[int] = None,
) -> Optional[int]:
    """Cash forecast day-of-month.

    The locked day is the day the bill actually posts. If nothing is locked,
    use the most common posted day. ``lender_next_day`` is a period label
    (a lender "next payment" date) and never moves the forecast day.
    """
    del lender_next_day  # accepted so callers cannot "forget" and use it instead
    if locked_day is not None:
        day = int(locked_day)
        if 1 <= day <= 31:
            return day
    days = []
    for raw in posted_days or []:
        try:
            day = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= day <= 31:
            days.append(day)
    if days:
        return int(Counter(days).most_common(1)[0][0])
    return None


def is_unverified_feed(source: Optional[str]) -> bool:
    """True when a row comes from an observed or unverified feed.

    Those rows must not be promoted into the verified forecast. Blank sources
    stay allowed so hand-entered actuals and statement lines without a tag
    still count. Pics and statement exports are not unverified.
    """
    s = (source or "").strip().lower()
    if not s:
        return False
    if s in _UNVERIFIED_EXACT:
        return True
    return any(
        s.startswith(prefix + sep)
        for prefix in _UNVERIFIED_PREFIXES
        for sep in (":", "_", "-", "/")
    )


def relabel_changes_cash(old_amount: float, new_amount: float) -> bool:
    """Classification edits do not move cash unless the amount itself changes."""
    return float(old_amount) != float(new_amount)


def source_updates_account(source_account: str, target_account: str) -> bool:
    """One source may update only the account it is a picture or export of."""
    return (source_account or "").strip().casefold() == (target_account or "").strip().casefold()


def card_owed_once(
    *,
    limit: Optional[float] = None,
    available: Optional[float] = None,
    posted: Optional[float] = None,
    pending: Optional[float] = None,
    current: Optional[float] = None,
) -> Optional[float]:
    """Card amount owed, counting pending once.

    When limit and available are both known, owed is limit minus available.
    Available already reserves pending, so pending is not added again.
    That figure wins over posted+pending and over a current-balance label
    when they disagree. If only posted and pending are known, add pending
    once. ``current`` is a last resort and is never stacked on top of pending.
    """
    path_a = None
    if limit is not None and available is not None:
        path_a = round(float(limit) - float(available), 2)
    path_b = None
    if posted is not None and pending is not None:
        path_b = round(float(posted) + float(pending), 2)
    elif posted is not None:
        path_b = round(float(posted), 2)
    if path_a is not None:
        return path_a
    if path_b is not None:
        return path_b
    if current is not None:
        return round(float(current), 2)
    return None


def collapse_same_visit_pending(items: Optional[list]) -> list:
    """Keep one pending line per card visit.

    Lines that share ``visit_id`` collapse to a single line. Prefer a
    tip-final or posted amount over the pre-tip authorization and over a
    stale pending copy. Do not sum those stages. Lines with no visit id
    are left unchanged.
    """
    if not items:
        return []
    passthrough: list = []
    groups: dict[str, list] = {}
    for item in items:
        if not isinstance(item, dict):
            passthrough.append(item)
            continue
        visit = str(item.get("visit_id") or "").strip()
        if not visit:
            passthrough.append(item)
            continue
        groups.setdefault(visit, []).append(item)
    collapsed = list(passthrough)
    for group in groups.values():
        def _rank(it: dict) -> int:
            role = str(it.get("role") or it.get("stage") or "").strip().lower()
            return _VISIT_RANK.get(role, 15)

        collapsed.append(max(group, key=_rank))
    return collapsed


def posted_card_actuals_from_pending_header(header_total: Any) -> list[dict]:
    """A pending header is not a posted ledger. Never synthesize card actuals."""
    del header_total
    return []


def is_pending_card_status(status: Optional[str]) -> bool:
    """Pending / auth rows are not posted card actuals."""
    return (status or "").strip().lower() in _PENDING_CARD_STATUSES
