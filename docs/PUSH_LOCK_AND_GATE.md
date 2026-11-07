# Safety rails: push lock, pre-push gate, integrity gate, failure log, rollback

These are general rails for any household using this engine. Nothing here holds household data.

## 1. Turn the gate on (once per clone)
```bash
git config core.hooksPath .githooks
```
Never bypass it with `--no-verify`, never force-push, and never loosen a test to get green. Fix the cause.

## 2. Working-tree lock
`scripts/with_push_lock.sh <command>` runs a commit, push or data-writing job while holding one `flock` file
(default `.git/hce-push.lock`, never committed). Anything that writes tracked files (imports, refresh jobs) wraps its
write step the same way, so it can never rewrite `data/` in the middle of the test suite. A bare `git push` is still
safe: the hook warns and takes the lock itself.

## 3. Pre-push gate (`.githooks/pre-push`)
Order: lock, privacy guard, full pytest (`-n auto` when pytest-xdist is installed), `engine.prod_gate`, rules ledger
drift check. Any failure blocks the push. Full timestamped output is kept in `~/.hce-prepush-logs/` (override with
`HCE_PREPUSH_LOGDIR`). A block appends to `failures.jsonl` there and prints known causes from `docs/FAILURE_LOG.md`.

## 4. Integrity gate (`engine/prod_gate.py`)
Runs the forecast on a temporary copy of the database. Blocks when a planned item and an actual are the same money
counted twice, or (with a before snapshot) when a change adds a red month or lowers the low point without a stated reason.
```bash
python -m engine.prod_gate --write-snapshot /tmp/before.json      # before the change
python -m engine.prod_gate --compare-snapshot /tmp/before.json    # after
python -m engine.prod_gate --compare-snapshot /tmp/before.json --accept "new car payment starts in March"
```

## 5. Failure log and weekly trend
Every blocked push gets one entry in `docs/FAILURE_LOG.md` (strict format, enforced by `tests/test_failure_log.py`).
```bash
python scripts/failure_summary.py           # top causes by time lost
python scripts/failure_summary.py --trend   # weekly review: rising causes, test files that keep coming back
```

## 6. Live check and rollback switch
After every push: reboot the app, open it, and confirm the approved figures (balance, low point, red months) match what
you signed off. Only then record the release as good:
```bash
python scripts/rollback_to_good.py mark-good
```
If a later release is wrong: `rollback_to_good.py status`, then `prepare`. It backs up your data outside the repo and
builds normal revert commits on a new `rollback/<time>` branch. It never resets, never force-pushes and never pushes.
A commit that changed data is never reverted automatically, so approved bookings are never erased.
`rollback_to_good.py rehearse` proves all of this on a throwaway synthetic repo.

## 7. Rules ledger
`docs/DECISIONS_LEDGER.md` lists every household rule with the test that enforces it. `scripts/rules_drift_check.py`
fails when an active rule has no test, when ids repeat, or when a picture or real database is tracked by git.
