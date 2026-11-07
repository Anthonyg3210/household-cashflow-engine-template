"""Failure-log guard: repeated overnight/push failures are logged, with cause + time lost, in
docs/FAILURE_LOG.md so the top causes can be killed at the source (scripts/failure_summary.py).

Fails if (1) an entry is malformed, (2) a LEARNINGS reference points nowhere, (3) the pre-push hook recorded a gate failure on this machine
(``$HCE_PREPUSH_LOGDIR/failures.jsonl``, default ~/.hce-prepush-logs) on a day that has no log entry.
(3) is skipped on a clean clone where that file does not exist.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import failure_summary as fs  # noqa: E402

LOG_TEXT = (ROOT / "docs" / "FAILURE_LOG.md").read_text()
_LP = ROOT / "docs" / "LEARNINGS.md"
LEARN = _LP.read_text() if _LP.exists() else ""


def _entries():
    return fs.parse(LOG_TEXT)


def test_every_entry_is_well_formed():
    es = _entries()
    assert es, "keep at least the example entry so the format stays documented"
    ids = [e["id"] for e in es]
    assert ids == [f"FL-{i:03d}" for i in range(1, len(es) + 1)], "ids must be FL-001.. in order, no gaps or reuse"
    for e in es:
        f = e["fields"]
        missing = [k for k in fs.FIELDS if not f.get(k)]
        assert not missing, f"{e['id']} missing {missing}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["Date"]) and f["Date"] == e["head_date"], e["id"]
        assert f["Cause class"] in fs.CLASSES, f"{e['id']}: Cause class must be one of {sorted(fs.CLASSES)}"
        assert (fs.parse_minutes(f["Time lost"]) or 0) > 0, f"{e['id']}: Time lost like 6h, 1h20m, 45m"
        assert re.search(r"`(tests/[\w./]+\.py|prod_gate)[^`]*`", f["Failing test"]), f"{e['id']}: name the failing test in backticks"
        assert len(f["Root cause"]) > 20 and len(f["Corrective action"]) > 20, e["id"]


def test_logged_learnings_headings_exist():
    heads = re.findall(r"^## (.+)$", LEARN, re.M)
    for e in _entries():
        ref = e["fields"].get("LEARNINGS", "")
        if ref and ref.lower() != "none":
            assert any(h.startswith(ref) for h in heads), f"{e['id']}: LEARNINGS heading {ref!r} not found"


def test_every_recorded_hook_failure_day_has_a_log_entry():
    p = Path(os.environ.get("HCE_PREPUSH_LOGDIR", str(Path.home() / ".hce-prepush-logs"))) / "failures.jsonl"
    if not p.exists():
        return  # clean clone / CI: nothing recorded
    dates = {e["fields"]["Date"] for e in _entries()}
    for line in p.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("note_only"):
            continue
        day = rec["ts"][:10]
        assert day in dates, (f"pre-push gate failed on {day} ({rec.get('stage')}, log {rec.get('log')}) "
                              "but docs/FAILURE_LOG.md has no entry for that day")
