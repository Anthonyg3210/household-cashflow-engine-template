#!/usr/bin/env python3
"""Privacy guard for the public Household Cashflow Engine template: blocks any real household value.

Two layers:
  1. Generic checks (always on, no private data needed): account-like digit runs, emails that are not example.*,
     US phone numbers, SSN-like numbers, "ending in" / "last four" card-digit mentions, Plaid-style ids.
  2. Private denylist (``--private-repo PATH``): DERIVED AT RUN TIME from the private production repo's data
     (account/loan/policy/member numbers, people and payee names, employer, card names, the cities on card
     descriptors, and every exact dollar amount with cents from balances, debts, income, rules and retirement
     files). Nothing from it is ever written into this repo: the list lives only in memory.

Scans every tracked file (text, and SQLite databases dumped to text) and, with ``--history``, every blob in every
commit, including this script itself. Exit 1 on any hit. Hits print the file and a masked hint, never the value.
Household-specific words never live in this file: extra private terms (and extra stopwords) come only from the
``--extra-terms`` JSON kept outside the repo.

    python scripts/privacy_guard.py                                  # generic layer, working tree
    python scripts/privacy_guard.py --private-repo ../private --history
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- layer 1: generic patterns
GENERIC = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)(?!users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "us_phone": re.compile(r"(?<![\d.])(?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}(?![\d.])"),
    "ssn": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "account_digits": re.compile(r"(?<![\d.,$])(?:[A-Z]{1,2})?\d{8,17}(?![\d.])"),
    "ending_in": re.compile(r"(?i)\b(?:ending(?: in)?|last ?4|last four|x{2,}|\*{2,})[\s:#-]*\d{4}\b(?![-/]\d)"),
}
# fictitious / technical strings the generic layer may see (dates, hashes, version pins)
GENERIC_OK = re.compile(r"^(?:20\d{6}|19\d{6}|\d{8,}$)")


def _date_like(s: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])(?:\d{4,6})?", s))


# ---------------------------------------------------------------- layer 2: private denylist (derived, never stored)
ID_KEY = re.compile(r"acct|account|mask|ending|number|loan|policy|routing|member|last4|last_4", re.I)
NAME_KEY = re.compile(r"(?:^|_)(?:owner|employer|dependents?|payee|spouse|person|holder|borrower|first_name|last_name|full_name)(?:_|$)", re.I)
AMOUNT_KEY = re.compile(r"balance|amount|payment|principal|escrow|interest|value|gross|net|salary|pay|minimum|limit|total|market", re.I)
GENERIC_WORDS = {
    "THE", "AND", "FOR", "PAY", "PAYMENT", "CARD", "PLAN", "BANK", "MORTGAGE", "FIRST",
    "SECOND", "PRIMARY", "BIWEEKLY", "MONTHLY", "BONUS", "HSA", "IRA", "ROTH", "LOAN", "CHECKING", "SAVINGS",
    "UNLIMITED", "VISA", "MASTERCARD", "INDIVIDUAL", "ZELLE", "FROM",
    "TO", "TRANSFER", "ONLINE", "MOBILE", "THANK", "YOU", "CREDIT", "DEBIT", "SPOUSE", "CHILD", "SON", "DAUGHTER",
    "MR", "MRS", "MS", "JR", "SR", "LLC", "INC", "CO", "USA", "US", "ACH", "WEB", "PPD", "ID", "NONE", "NULL",
    "RETIREMENT", "TECHNOLOGIES", "CAFE", "COFFEE", "GRILL", "PIZZA", "MARKET", "STORE", "SHOP", "KITCHEN", "BAR",
    "RESTAURANT", "BLVD", "ROAD", "PARKWAY", "PKWY", "PLAZA", "MALL", "CENTER", "BEACH", "LAKE", "PARK",
}
# two-letter US state / DC codes: a card descriptor ending "<CITY> <ST>" names the city
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
                "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()) - {"IN", "OR", "ME", "OK", "HI", "DE", "CO", "ID"}


def _walk(o, key="", path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(v, str(k), f"{path}/{k}")
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, key, path)
    else:
        yield key, o, path


def _money_forms(x: float) -> set[str]:
    a = abs(round(float(x), 2))
    if a < 100 or round(a * 100) % 100 == 0:  # only non-round amounts of $100+ are identifying
        return set()
    return {f"{a:.2f}", f"{a:,.2f}"}


def derive_private(private: Path) -> dict[str, set[str]]:
    d = private / "data"
    ids, names, cities, amounts = set(), set(), set(), set()
    for f in sorted(d.glob("*.json")):
        try:
            obj = json.loads(f.read_text())
        except Exception:
            continue
        for k, v, path in _walk(obj):
            if isinstance(v, str):
                if ID_KEY.search(k) and re.search(r"\d{4,}", v) and len(v) <= 40:
                    ids.update(re.findall(r"[A-Za-z]{0,3}\d{4,}", v))
                if (NAME_KEY.search(k) or (k == "name" and re.search(r"(?:^|/)(?:dependents?|owner|person|spouse)(?:/|$)", path, re.I))) and len(v) <= 60:
                    names.update(w for w in re.findall(r"[A-Za-z0-9]*[A-Za-z]{3,}", v) if w.upper() not in GENERIC_WORDS)
                if re.search(r"rate|apr", k, re.I) and re.fullmatch(r"\d{1,2}\.\d{2,4}", v.strip().rstrip("%")):
                    amounts.add(v.strip().rstrip("%"))
                ids.update(re.findall(r"\b[A-Z]\d{8}\b", v))  # brokerage-style account numbers anywhere
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                if ID_KEY.search(k) and isinstance(v, int) and v >= 1000:
                    ids.add(str(v))
                if AMOUNT_KEY.search(k):
                    amounts |= _money_forms(v)
                if re.search(r"rate|apr", k, re.I) and isinstance(v, float) and 1 < v < 40 and round(v, 2) != round(v, 0):
                    amounts.add(f"{v}")
    for f in ("accounts.csv", "debts.csv", "income.csv"):
        p = d / f
        if not p.exists():
            continue
        for row in csv.DictReader(io.StringIO(p.read_text())):
            for k, v in row.items():
                try:
                    amounts |= _money_forms(float(v))
                except (TypeError, ValueError):
                    pass
            if f == "income.csv" and row.get("source"):
                w = row["source"].split()[0]
                if w.upper() not in GENERIC_WORDS and w.isalpha():
                    names.add(w)
            for v in row.values():
                ids.update(re.findall(r"\b[A-Z]\d{8}\b", v or ""))
    db = d / "cashflow.db"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for (amt,) in con.execute("SELECT amount FROM recurring_rules"):
                amounts |= _money_forms(amt or 0)
            for (desc,) in con.execute("SELECT COALESCE(label,'') || ' ' || COALESCE(memo,'') FROM actuals WHERE (label || memo) LIKE '%Zelle%'"):
                m = re.search(r"(?i)zelle (?:payment )?(?:to|from) ([A-Za-z]+(?: [A-Za-z]+)?)", desc or "")
                if m:
                    names.update(w for w in m.group(1).split() if w.upper() not in GENERIC_WORDS and len(w) >= 3)
        finally:
            con.close()
    for led in sorted(d.glob("*ledger*.json")):  # card ledgers: rows[].description like "MERCHANT CITY ST"
        try:
            rows = json.loads(led.read_text()).get("rows", [])
        except Exception:
            continue
        for r in rows if isinstance(rows, list) else []:
            for w, st in re.findall(r"\b([A-Z]{4,})\s+([A-Z]{2})\b", (r.get("description") or "").upper()):
                if st in US_STATES and w not in GENERIC_WORDS:
                    cities.add(w)
    # the household surname: the private repo's own name, e.g. smith-cashflow-twin
    sur = re.match(r"([a-z]{3,})-", private.resolve().name)
    if sur:
        names.add(sur.group(1).capitalize())
    return {"id": {i for i in ids if len(re.sub(r"\D", "", i)) >= 4},
            "name": {n for n in names if len(n) >= 3},
            "city": cities, "amount": amounts}


def load_extra(path: Path | None) -> dict[str, set[str]]:
    """Optional PRIVATE term list (kept outside this repo): {"terms": [...], "numbers": [...], "stopwords": [...]}."""
    if not path:
        return {}
    d = json.loads(Path(path).read_text())
    GENERIC_WORDS.update(w.upper() for w in d.get("stopwords") or [])
    global ID_KEY
    if d.get("id_keys"):  # extra private JSON key fragments that hold ids
        ID_KEY = re.compile(ID_KEY.pattern + "|" + "|".join(re.escape(k) for k in d["id_keys"]), re.I)
    return {"term": set(d.get("terms") or []), "number": set(d.get("numbers") or [])}


def _compile(deny: dict[str, set[str]]):
    out = []
    for kind, vals in deny.items():
        for v in sorted(vals):
            if kind in ("amount", "number"):
                pat = re.compile(r"(?<![\d.,])" + re.escape(v) + r"(?![\d])")
            else:
                pat = re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])")
            out.append((kind, v, pat))
    return out


# ---------------------------------------------------------------- file text
def _sqlite_text(raw: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".db") as t:
        t.write(raw); t.flush()
        con = sqlite3.connect(t.name)
        try:
            return "\n".join(con.iterdump())
        finally:
            con.close()


def _text(raw: bytes) -> str | None:
    if raw.startswith(b"SQLite format 3\x00"):
        return _sqlite_text(raw)
    if b"\x00" in raw[:4096]:
        return None  # other binaries (images) are not text
    return raw.decode("utf-8", "replace")


def _mask(v: str) -> str:
    return v[0] + "…" + f"({len(v)} chars)" if v else "?"


def scan_text(label: str, text: str, deny) -> list[str]:
    hits = []
    for kind, pat in GENERIC.items():
        for m in pat.finditer(text):
            s = m.group(0)
            if kind == "account_digits":
                j = m.start()
                while j > 0 and text[j - 1].isalpha():
                    j -= 1
                if _date_like(re.sub(r"\D", "", s)) or text[j:m.end()].upper().startswith("DEMO"):
                    continue  # dates, and fictitious DEMO000… ids
            hits.append(f"{label}: generic {kind} {_mask(s)}")
    for kind, v, pat in deny:
        if pat.search(text):
            hits.append(f"{label}: private {kind} {_mask(v)}")
    return hits


def tracked(repo: Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True)
    return [x for x in r.stdout.decode().split("\0") if x]


def history_blobs(repo: Path) -> list[tuple[str, str]]:
    r = subprocess.run(["git", "-C", str(repo), "rev-list", "--objects", "--all"], capture_output=True, text=True, check=True)
    out = []
    for line in r.stdout.splitlines():
        sha, _, path = line.partition(" ")
        if path:
            t = subprocess.run(["git", "-C", str(repo), "cat-file", "-t", sha], capture_output=True, text=True).stdout.strip()
            if t == "blob":
                out.append((sha, path))
    return out


def run(repo: Path, private: Path | None, history: bool, allow: set[str] | None = None,
        extra: Path | None = None) -> list[str]:
    ext = load_extra(extra)  # first: its stopwords shape what derive_private keeps
    deny = _compile({**(derive_private(private) if private else {}), **ext})
    hits = []
    skip: set[str] = set()  # scans itself too: no household terms may live in this file
    for rel in tracked(repo):
        if rel in skip:
            continue
        p = repo / rel
        if not p.is_file():
            continue
        t = _text(p.read_bytes())
        if t is not None:
            hits += scan_text(rel, t, deny)
    if history:
        seen = set()
        for sha, path in history_blobs(repo):
            if sha in seen or path in skip:
                continue
            seen.add(sha)
            raw = subprocess.run(["git", "-C", str(repo), "cat-file", "-p", sha], capture_output=True).stdout
            t = _text(raw)
            if t is not None:
                hits += [f"history {sha[:8]} " + h for h in scan_text(path, t, deny)]
    if allow:
        hits = [h for h in hits if not any(a in h for a in allow)]
    return sorted(set(hits))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--private-repo", default=None)
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--extra-terms", default=None, help="private JSON term list kept OUTSIDE this repo")
    ap.add_argument("--counts", action="store_true", help="print how many private values were derived (no values)")
    a = ap.parse_args(argv)
    priv = Path(a.private_repo) if a.private_repo else None
    if priv and a.counts:
        print({k: len(v) for k, v in derive_private(priv).items()})
    hits = run(Path(a.repo), priv, a.history, extra=Path(a.extra_terms) if a.extra_terms else None)
    for h in hits:
        print(h)
    print(f"privacy guard: {'BLOCKED' if hits else 'CLEAN'} ({len(hits)} hits; private layer {'on' if priv else 'off'}; "
          f"history {'on' if a.history else 'off'})")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
