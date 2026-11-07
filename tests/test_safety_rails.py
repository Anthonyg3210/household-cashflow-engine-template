"""General safety rails: integrity gate, rules ledger, push lock and pre-push hook. Synthetic data only."""
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from engine import db, prod_gate, rules_ledger

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "sample" / "demo_bootstrap.db"


def _copy(tmp_path):
    p = tmp_path / "t.db"
    shutil.copy2(DEMO, p)
    return p


def test_prod_gate_passes_on_demo_data():
    rc, snap, problems = prod_gate.run(DEMO)
    assert rc == 0, problems
    assert snap["months"] > 0


def test_prod_gate_never_writes_the_source_db(tmp_path):
    p = _copy(tmp_path)
    before = p.read_bytes()
    prod_gate.run(p)
    assert p.read_bytes() == before


def test_prod_gate_blocks_double_count(tmp_path):
    p = _copy(tmp_path)
    conn = db.connect(p, restore_bootstrap=False)
    db.init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(actuals)")}
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(planned_items)")}
    a = {"date": "2030-01-15", "amount": -123.45, "category": "Example Bill"}
    conn.execute(f"INSERT INTO actuals ({','.join(k for k in a if k in cols)}) VALUES ({','.join('?' for k in a if k in cols)})",
                 [v for k, v in a.items() if k in cols])
    pa = dict(a, label="Example Bill")
    conn.execute(f"INSERT INTO planned_items ({','.join(k for k in pa if k in pcols)}) VALUES ({','.join('?' for k in pa if k in pcols)})",
                 [v for k, v in pa.items() if k in pcols])
    conn.commit()
    conn.close()
    rc, _, problems = prod_gate.run(p)
    assert rc == 1 and any("both planned and actual" in x for x in problems)


def test_prod_gate_compare_flags_new_red_month():
    before = {"red_months": [], "min_eod": 500.0, "months": 12}
    after = {"red_months": ["2027-03"], "min_eod": -20.0, "months": 12}
    probs = prod_gate.compare(before, after)
    assert any("2027-03" in p for p in probs) and any("low point" in p for p in probs)
    assert prod_gate.compare(before, after, accept="example: planned car purchase") == []
    assert prod_gate.compare(before, dict(before)) == []


def test_rules_ledger_is_clean():
    f = rules_ledger.findings()
    assert not f["errors"], f["errors"]
    assert f["rules"] >= 1


def test_rules_ledger_flags_missing_test_and_images(tmp_path):
    led = tmp_path / "L.md"
    led.write_text("| R-01 | x | Active | `tests/test_nope.py::test_x` |\n| R-01 | y | Pending | |\n")
    f = rules_ledger.findings(led, tracked=["app.py", "pics/bank.png", "data/real.db"])
    errs = " ".join(f["errors"])
    assert "more than once" in errs and "does not exist" in errs and "bank.png" in errs and "real.db" in errs
    assert f["notes"]


def test_pre_push_hook_runs_every_gate_and_unsets_git_env():
    hook = (ROOT / ".githooks" / "pre-push").read_text()
    for step in ("privacy_guard.py", "-m pytest", "engine.prod_gate", "rules_drift_check.py", "flock",
                 "unset GIT_DIR GIT_INDEX_FILE", "failures.jsonl"):
        assert step in hook, step
    assert "--no-verify" not in hook.replace("Never bypass with --no-verify", "")
    assert os.access(ROOT / ".githooks" / "pre-push", os.X_OK)


def test_pre_push_hook_blocks_on_failing_gate(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HCE_PREPUSH_CMD"] = "exit 3"
    r = subprocess.run(["bash", str(ROOT / ".githooks" / "pre-push")], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "BLOCKED" in r.stderr


def test_with_push_lock_sets_held_flag(tmp_path):
    if not shutil.which("flock"):
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HCE_PUSH_LOCK"] = str(tmp_path / "l.lock")
    r = subprocess.run([str(ROOT / "scripts" / "with_push_lock.sh"), "bash", "-c", "echo $HCE_PUSH_LOCK_HELD"],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.stdout.strip() == "1"
