"""Weekly FAILURE_LOG trend : scripts/failure_summary.py --trend.

Monday failure review reads per-week entries and time lost by cause class, rising classes and test files that keep
coming back. Synthetic entries only; the real log is read, never written."""
import importlib.util
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("failure_summary", ROOT / "scripts" / "failure_summary.py")
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)


def _e(i, d, cls, mins, test):
    return {"id": f"FL-{i:03d}", "head_date": d, "title": "t",
            "fields": {"Date": d, "Cause class": cls, "Time lost": f"{mins}m", "Failing test": f"`{test}::test_x`"}}


def test_trend_counts_rising_and_repeats():
    entries = [_e(1, "2026-10-27", "flaky", 10, "tests/test_a.py"),
               _e(2, "2026-11-02", "flaky", 15, "tests/test_a.py"),
               _e(3, "2026-11-04", "flaky", 20, "tests/test_a.py"),
               _e(4, "2026-11-08", "process", 5, "tests/test_b.py"),  # Sunday: still week of Nov 2
               _e(5, "2026-11-09", "stale-pin", 5, "tests/test_b.py")]  # next week: outside the window
    t = fs.trend(entries, weeks=2, today=date(2026, 11, 7))
    assert t["weeks"] == [("2026-10-26", 1, 10, {"flaky": 1}), ("2026-11-02", 3, 40, {"flaky": 2, "process": 1})]
    assert t["rising"] == ["flaky"] and t["direction"] == "up"
    assert t["repeat_files"] == {"tests/test_a.py": ["FL-001", "FL-002", "FL-003"]}


def test_single_entry_class_is_not_called_rising():
    entries = [_e(1, "2026-11-03", "engine-bug", 10, "tests/test_a.py")]
    assert fs.trend(entries, weeks=2, today=date(2026, 11, 7))["rising"] == []


def test_trend_runs_on_the_real_log(capsys):
    assert fs.main(["--trend", "--today", "2026-01-07"]) == 0
    out = capsys.readouterr().out
    assert "weekly trend" in out and "week of 2026-01-05" in out


def test_hint_runs_without_a_log(capsys):
    assert fs.main(["--hint"]) == 0
