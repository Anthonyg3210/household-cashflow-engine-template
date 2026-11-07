#!/usr/bin/env python3
"""Rollback switch: return production code to the last verified-good release WITHOUT rewriting history .

  python scripts/rollback_to_good.py status              # last verified-good, HEAD, and what changed since
  python scripts/rollback_to_good.py backup              # cashflow.db + bootstrap + config with a hash manifest
  python scripts/rollback_to_good.py prepare             # backup, then revert commits on a new rollback/<ts> branch
  python scripts/rollback_to_good.py prepare --commits a1b2c3d,e4f5a6b   # revert only these code commits
  python scripts/rollback_to_good.py mark-good           # record HEAD as verified-good after a live check
  python scripts/rollback_to_good.py rehearse            # full dry rehearsal on a synthetic repo (no real data)

How it stays safe:
* Only normal ``git revert`` commits on a new local branch. Never reset, never force-push, never push at all: the
  household agent merges the branch into main and pushes through the pre-push gate like any release.
* A commit since the verified-good release that touches data (``data/``, ``seed/``) or the approved picture
  (``tests/pins.json`` if your household pins figures) is NOT reverted automatically: reverting it would erase an approved
  booking. ``prepare`` stops (exit 4) and lists them; revert the code commits only with ``--commits`` and keep the
  bookings, or ask the household owner.
* ``backup`` copies the gitignored Verified DB (``data/cashflow.db``) and the tracked bootstrap/config with SHA-256
  hashes to ~/.hce-rollback-backups/<ts>/ (outside the repo; real data never goes to GitHub).
* Verified-good releases are recorded with ``mark-good`` AFTER you have checked the live app matches the approved
  figures, in ~/.hce-answer-keys/verified_good.jsonl (outside the repo).

After ``prepare``: prod_gate --write-snapshot (before) on main; ``git merge --ff-only rollback/<ts>``; prod_gate
--compare-snapshot; push through the hook; reboot; check the live figures; ``mark-good``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOOD_FILE = Path(os.environ.get("HCE_ANSWER_KEY_DIR", str(Path.home() / ".hce-answer-keys"))) / "verified_good.jsonl"
BACKUP_DIR = Path(os.environ.get("HCE_ROLLBACK_BACKUP_DIR", str(Path.home() / ".hce-rollback-backups")))
DATA_PREFIXES = ("data/", "seed/")
APPROVED_PICTURE = ("tests/pins.json",)
BACKUP_FILES = ("data/cashflow.db", "data/cloud_bootstrap.db", "data/live_checking.json", "data/debts.json",
                "data/payment_preferences.json", "data/merchant_map.json")


class RollbackStop(Exception):
    """Rollback refused: history or data could be lost. The message says why."""


def git(repo: Path, *args: str, check: bool = True) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RollbackStop(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def is_ancestor(repo: Path, rev: str) -> bool:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", rev, "HEAD"], env=env,
                          capture_output=True).returncode == 0


def record_good(revision: str, data_hash: str, verified_at: str, good_file: Path | None = None) -> None:
    gf = good_file or GOOD_FILE
    gf.parent.mkdir(parents=True, exist_ok=True)
    with open(gf, "a") as fh:
        fh.write(json.dumps({"revision": revision, "data_hash": data_hash, "verified_at": verified_at}) + "\n")


def last_good(good_file: Path | None = None) -> dict | None:
    gf = good_file or GOOD_FILE
    if not gf.is_file():
        return None
    rows = [json.loads(l) for l in gf.read_text().splitlines() if l.strip()]
    return rows[-1] if rows else None


def classify(repo: Path, good: str) -> list[dict]:
    """Commits after ``good`` up to HEAD (newest first) with the kind of files each touches."""
    if not is_ancestor(repo, good):
        raise RollbackStop(f"verified-good {good[:12]} is not an ancestor of HEAD; refusing")
    out = []
    for sha in git(repo, "rev-list", "--no-merges", f"{good}..HEAD").splitlines():
        files = git(repo, "show", "--name-only", "--pretty=format:", sha).splitlines()
        files = [f for f in files if f]
        data = [f for f in files if f.startswith(DATA_PREFIXES) or f in APPROVED_PICTURE]
        kind = "code" if not data else ("data" if len(data) == len(files) else "mixed")
        out.append({"sha": sha, "subject": git(repo, "log", "-1", "--pretty=%s", sha), "kind": kind, "data_files": data})
    merges = git(repo, "rev-list", "--merges", f"{good}..HEAD")
    if merges:
        raise RollbackStop(f"merge commits since verified-good ({merges.split()[0][:12]}…); revert by hand with -m after review")
    return out


def backup(repo: Path, dest_root: Path | None = None) -> Path:
    dest = (dest_root or BACKUP_DIR) / dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dest.mkdir(parents=True, exist_ok=False)
    manifest = {"made_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "head": git(repo, "rev-parse", "HEAD"), "files": {}}
    for f in BACKUP_FILES:
        src = repo / f
        if src.is_file():
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / f)
            manifest["files"][f] = hashlib.sha256(src.read_bytes()).hexdigest()
    for f, h in manifest["files"].items():  # verify the copy before relying on it
        if hashlib.sha256((dest / f).read_bytes()).hexdigest() != h:
            raise RollbackStop(f"backup copy of {f} does not match its hash")
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    return dest


def prepare(repo: Path, good: str, commits: list[str] | None = None, backup_root: Path | None = None) -> dict:
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise RollbackStop("working tree has uncommitted changes to tracked files; commit or stash them first")
    plan = classify(repo, good)
    if commits:
        full = {git(repo, "rev-parse", c) for c in commits}
        known = {p["sha"] for p in plan}
        if not full <= known:
            raise RollbackStop("--commits must be commits made after the verified-good release")
        chosen = [p for p in plan if p["sha"] in full]
    else:
        chosen = plan
    risky = [p for p in chosen if p["kind"] != "code"]
    if risky:
        raise RollbackStop("these commits change data or the approved picture; reverting them would erase approved "
                           "bookings: " + "; ".join(f"{p['sha'][:9]} {p['subject']} ({', '.join(p['data_files'][:3])})" for p in risky))
    if not chosen:
        raise RollbackStop("nothing to revert: HEAD is the verified-good release")
    bdir = backup(repo, backup_root)
    branch = f"rollback/{dt.datetime.now().strftime('%Y%m%dT%H%M%S%f')}"
    # Build the reverts in a separate worktree so the production checkout (which the polls pull into) never leaves main.
    wt = Path(tempfile.mkdtemp(prefix="hce-rollback-wt-")) / "wt"
    git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "HEAD")
    try:
        for p in chosen:  # newest first
            git(wt, "revert", "--no-edit", p["sha"])
    except RollbackStop:
        git(wt, "revert", "--abort", check=False)
        raise
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
    return {"branch": branch, "reverted": [p["sha"] for p in chosen], "backup": str(bdir), "good": good}


def _commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for f, text in files.items():
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def rehearse(work: Path | None = None) -> dict:
    """Synthetic rehearsal: good release, then a bad code commit and an approved booking. Proves (1) a data commit
    stops the automatic rollback, (2) a code-only rollback restores the good code and keeps the newer booking,
    (3) history is only appended to."""
    tmp = Path(work or tempfile.mkdtemp(prefix="hce-rollback-rehearsal-"))
    repo = tmp / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "rehearsal@example.com")
    git(repo, "config", "user.name", "rollback rehearsal")
    good = _commit(repo, {"engine/calc.py": "RATE = 10\n", "data/cashflow.db": "synthetic-v1\n",
                          "data/key_numbers.json": "{}\n"}, "good release")
    bad = _commit(repo, {"engine/calc.py": "RATE = 0  # bug\n"}, "bad code")
    _commit(repo, {"data/cashflow.db": "synthetic-v2 (approved booking)\n"}, "approved booking")
    n_before = int(git(repo, "rev-list", "--count", "HEAD"))
    stopped = False
    try:
        prepare(repo, good, backup_root=tmp / "backups")
    except RollbackStop:
        stopped = True
    head_before = git(repo, "rev-parse", "HEAD")
    res = prepare(repo, good, commits=[bad], backup_root=tmp / "backups")
    untouched = git(repo, "rev-parse", "HEAD") == head_before and git(repo, "branch", "--show-current") == "main"
    git(repo, "merge", "--ff-only", "-q", res["branch"])  # the normal release step
    ok = {
        "production_checkout_untouched_until_merge": untouched,
        "data_commit_stopped_automatic_rollback": stopped,
        "code_restored": (repo / "engine/calc.py").read_text() == "RATE = 10\n",
        "newer_booking_kept": (repo / "data/cashflow.db").read_text().startswith("synthetic-v2"),
        "history_only_appended": int(git(repo, "rev-list", "--count", "HEAD")) == n_before + 1,
        "good_commit_still_in_history": is_ancestor(repo, good),
        "backup_manifest": (Path(res["backup"]) / "MANIFEST.json").is_file(),
    }
    return {"ok": all(ok.values()), "checks": ok, "work": str(tmp)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("backup")
    pp = sub.add_parser("prepare")
    pp.add_argument("--to", help="verified-good revision (default: last recorded)")
    pp.add_argument("--commits", help="comma-separated code commits to revert (default: all since good)")
    sub.add_parser("rehearse")
    mg = sub.add_parser("mark-good")
    mg.add_argument("--revision", default="HEAD")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "rehearse":
            r = rehearse()
            for k, v in r["checks"].items():
                print(f"{'OK ' if v else 'FAIL'} {k}")
            print("Rehearsal PASS" if r["ok"] else "Rehearsal FAIL")
            return 0 if r["ok"] else 1
        if a.cmd == "backup":
            print(f"Backup written: {backup(ROOT)}")
            return 0
        if a.cmd == "mark-good":
            rev = git(ROOT, "rev-parse", a.revision)
            h = hashlib.sha256(b"".join((ROOT / f).read_bytes() for f in BACKUP_FILES if (ROOT / f).is_file())).hexdigest()[:16]
            record_good(rev, h, dt.datetime.now().astimezone().isoformat(timespec="seconds"))
            print(f"Recorded verified-good {rev[:12]}")
            return 0
        good = getattr(a, "to", None) or (last_good() or {}).get("revision")
        if not good:
            print("No verified-good release recorded yet (check the live app, then: rollback_to_good.py mark-good).")
            return 4
        if a.cmd == "status":
            print(f"Last verified-good: {good[:12]}; HEAD {git(ROOT, 'rev-parse', 'HEAD')[:12]}")
            for p in classify(ROOT, good):
                print(f"  {p['sha'][:9]} [{p['kind']}] {p['subject']}")
            return 0
        res = prepare(ROOT, good, [c for c in (a.commits or "").split(",") if c])
        print(f"Rollback branch {res['branch']} reverts {len(res['reverted'])} commit(s) back to {good[:12]}.")
        print(f"Backup: {res['backup']}")
        print("Next: prod_gate before/after, merge --ff-only into main, push through the hook, reboot, answer key check.")
        return 0
    except RollbackStop as e:
        print(f"STOPPED: {e}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
