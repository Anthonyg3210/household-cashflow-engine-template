#!/usr/bin/env python3
"""Top failure causes by time lost, from docs/FAILURE_LOG.md (weekly review).

  python scripts/failure_summary.py                 # all history
  python scripts/failure_summary.py --since 2026-01-01
  python scripts/failure_summary.py --by test       # group by failing test file instead of cause class
  python scripts/failure_summary.py --hint [LOG]    # pre-push fail hint: top recent causes (+ match LOG)
  python scripts/failure_summary.py --trend         # weekly trend (Mon-Sun): entries + time lost per cause class,
                                                    # rising classes and repeat test files (Monday failure review)
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs" / "FAILURE_LOG.md"
ENTRY = re.compile(r"^### (FL-\d+) — (\d{4}-\d{2}-\d{2}) — (.+)$", re.M)
FIELDS = ("Date", "Failing test", "Root cause", "Cause class", "Corrective action", "Time lost", "LEARNINGS")
CLASSES = {"stale-pin", "stale-generated-data", "engine-bug", "process", "flaky", "environment"}
FAILED_LINE = re.compile(r"^(FAILED|ERROR)\s+(tests/\S+?)(?:\s|$)")


def parse_minutes(s: str) -> int | None:
    m = re.fullmatch(r"\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*", s.strip().split("  ")[0].split(" (")[0])
    if not m or not (m.group(1) or m.group(2)):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def parse(text: str) -> list[dict]:
    heads = list(ENTRY.finditer(text))
    out = []
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        e = {"id": h.group(1), "head_date": h.group(2), "title": h.group(3), "fields": {}}
        for f in FIELDS:
            m = re.search(rf"^- \*\*{re.escape(f)}:\*\* (.+)$", body, re.M)
            if m:
                e["fields"][f] = m.group(1).strip()
        out.append(e)
    return out


def fmt(mins: int) -> str:
    return f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m"


def summarize(entries: list[dict], by: str) -> tuple[dict, dict, dict, int]:
    tot, cnt, ids = defaultdict(int), defaultdict(int), defaultdict(list)
    for e in entries:
        mins = parse_minutes(e["fields"].get("Time lost", "")) or 0
        keys = [e["fields"].get("Cause class", "unclassified")] if by == "cause" else sorted(
            {re.sub(r"::.*", "", t) for t in re.findall(r"`([^`]+)`", e["fields"].get("Failing test", "")) or ["?"]})
        for k in keys:
            tot[k] += mins
            cnt[k] += 1
            ids[k].append(e["id"])
    grand = sum(parse_minutes(e["fields"].get("Time lost", "")) or 0 for e in entries)
    return tot, cnt, ids, grand


def print_summary(entries: list[dict], by: str, since: str) -> None:
    tot, cnt, ids, grand = summarize(entries, by)
    print(f"Failure log: {len(entries)} entries, {fmt(grand)} lost" + (f" since {since}" if since > "0" else ""))
    print(f"\nTop {'causes' if by == 'cause' else 'test files'} by time lost:")
    for k in sorted(tot, key=lambda k: (-tot[k], k)):
        pct = 100 * tot[k] / grand if grand else 0
        print(f"  {fmt(tot[k]):>7}  {pct:4.0f}%  {k}  ({cnt[k]} entr{'y' if cnt[k] == 1 else 'ies'}: {', '.join(ids[k])})")


def failing_tests_from_log(path: Path) -> list[str]:
    """Pull FAILED/ERROR test node ids from a pre-push pytest log (last occurrence wins order)."""
    if not path.is_file():
        return []
    seen, out = set(), []
    for line in path.read_text(errors="replace").splitlines():
        # stamped logs: "HH:MM:SS FAILED tests/foo.py::test_bar"
        body = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", line.strip())
        m = FAILED_LINE.match(body)
        if not m:
            continue
        node = m.group(2)
        file = node.split("::", 1)[0]
        if file not in seen:
            seen.add(file)
            out.append(file)
    return out


def hint(entries: list[dict], pytest_log: Path | None) -> int:
    """Smallest useful pre-push hint: recent cause classes + FAILURE_LOG matches for failing tests."""
    since = (date.today() - timedelta(days=30)).isoformat()
    recent = [e for e in entries if e["fields"].get("Date", e["head_date"]) >= since]
    print(f"=== Pre-push known-cause hint (FAILURE_LOG, last 30 days) ===")
    if not recent:
        print("(no FAILURE_LOG entries in the last 30 days)")
        return 0
    print_summary(recent, "cause", since)
    if pytest_log is None:
        return 0
    failed = failing_tests_from_log(pytest_log)
    if not failed:
        print(f"\n(no FAILED/ERROR test lines parsed from {pytest_log})")
        return 0
    print(f"\nMatching FAILURE_LOG hints for failing tests in this run:")
    any_hit = False
    for fpath in failed:
        short = Path(fpath).name
        hits = []
        for e in reversed(entries):  # newest first
            ft = e["fields"].get("Failing test", "")
            if short in ft or fpath in ft:
                hits.append(e)
                if len(hits) >= 3:
                    break
        if not hits:
            print(f"  {fpath}: (no prior FAILURE_LOG entry)")
            continue
        any_hit = True
        for e in hits:
            cls = e["fields"].get("Cause class", "?")
            cause = e["fields"].get("Root cause", e["title"])
            if len(cause) > 160:
                cause = cause[:157] + "..."
            print(f"  {fpath}: {e['id']} [{cls}] {cause}")
    if not any_hit:
        print("  (none of the failing tests have a prior FAILURE_LOG entry — check stale-pin / new regression)")
    print("Gate unchanged: fix the failure, then re-push. Log a new FAILURE_LOG entry if this is a new cause.")
    return 0


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def trend(entries: list[dict], weeks: int = 4, today: date | None = None) -> dict:
    """Last ``weeks`` Mon-Sun weeks ending with the week of ``today``: per week entries / minutes by cause class,
    classes rising week over week (this week > last week and at least 2 entries), and test files in 3+ entries."""
    today = today or date.today()
    starts = [week_start(today) - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    rows = {s: {"entries": 0, "minutes": 0, "by_class": defaultdict(int)} for s in starts}
    files = defaultdict(list)
    for e in entries:
        try:
            d = date.fromisoformat(e["fields"].get("Date", e["head_date"])[:10])
        except ValueError:
            continue
        ws = week_start(d)
        if ws not in rows:
            continue
        r = rows[ws]
        r["entries"] += 1
        r["minutes"] += parse_minutes(e["fields"].get("Time lost", "")) or 0
        r["by_class"][e["fields"].get("Cause class", "unclassified")] += 1
        for t in {re.sub(r"::.*", "", t) for t in re.findall(r"`(tests/[^`]+)`", e["fields"].get("Failing test", ""))}:
            files[t].append(e["id"])
    cur, prev = rows[starts[-1]], rows[starts[-2]] if len(starts) > 1 else None
    rising = sorted(c for c, n in cur["by_class"].items() if n >= 2 and prev is not None and n > prev["by_class"].get(c, 0))
    repeats = {f: ids for f, ids in sorted(files.items()) if len(ids) >= 3}
    return {"weeks": [(s.isoformat(), rows[s]["entries"], rows[s]["minutes"], dict(rows[s]["by_class"])) for s in starts],
            "rising": rising, "repeat_files": repeats,
            "direction": ("up" if prev and cur["entries"] > prev["entries"] else
                          "down" if prev and cur["entries"] < prev["entries"] else "flat")}


def print_trend(t: dict) -> None:
    print("Failure log weekly trend (weeks start Monday):")
    for ws, n, mins, by in t["weeks"]:
        parts = ", ".join(f"{k} {v}" for k, v in sorted(by.items(), key=lambda kv: (-kv[1], kv[0])))
        print(f"  week of {ws}: {n} entr{'y' if n == 1 else 'ies'}, {fmt(mins)} lost" + (f" ({parts})" if parts else ""))
    print(f"This week vs last week: {t['direction']}.")
    print("Rising cause classes: " + (", ".join(t["rising"]) if t["rising"] else "none"))
    if t["repeat_files"]:
        print("Test files in 3+ entries in this window (kill the cause at the source):")
        for f, ids in t["repeat_files"].items():
            print(f"  {f}: {', '.join(ids)}")
    else:
        print("No test file appears in 3+ entries in this window.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="0000-00-00")
    ap.add_argument("--by", choices=("cause", "test"), default="cause")
    ap.add_argument("--hint", nargs="?", const="", metavar="LOG",
                    help="pre-push fail hint: top recent cause classes; optional pytest log path to match failing tests")
    ap.add_argument("--trend", action="store_true", help="weekly trend by cause class (Monday failure review)")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    a = ap.parse_args(argv)
    entries = parse(LOG.read_text())
    if a.trend:
        print_trend(trend(entries, a.weeks, date.fromisoformat(a.today) if a.today else None))
        return 0
    if a.hint is not None:
        log_path = Path(a.hint) if a.hint else None
        return hint(entries, log_path)
    filtered = [e for e in entries if e["fields"].get("Date", e["head_date"]) >= a.since]
    print_summary(filtered, a.by, a.since)
    return 0


if __name__ == "__main__":
    sys.exit(main())
