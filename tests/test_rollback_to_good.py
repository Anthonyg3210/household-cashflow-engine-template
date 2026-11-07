"""Rollback switch : scripts/rollback_to_good.py, rehearsed on synthetic repos only.

Normal revert commits on a new branch built in a separate worktree; never reset, never force-push, never push.
A commit that changes data or the approved picture stops the automatic rollback so approved bookings are never erased."""
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("rollback_to_good", ROOT / "scripts" / "rollback_to_good.py")
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)


def test_rehearsal_on_synthetic_repo_passes_every_check(tmp_path):
    r = rb.rehearse(tmp_path)
    assert r["ok"], r["checks"]


def _repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    rb.git(repo, "init", "-q", "-b", "main")
    rb.git(repo, "config", "user.email", "t@example.com")
    rb.git(repo, "config", "user.name", "t")
    good = rb._commit(repo, {"engine/a.py": "x = 1\n"}, "good")
    return repo, good


def test_dirty_tree_is_refused(tmp_path):
    repo, good = _repo(tmp_path)
    rb._commit(repo, {"engine/a.py": "x = 2\n"}, "bad")
    (repo / "engine/a.py").write_text("x = 3\n")
    with pytest.raises(rb.RollbackStop, match="uncommitted"):
        rb.prepare(repo, good, backup_root=tmp_path / "b")


def test_approved_picture_change_stops_rollback(tmp_path):
    repo, good = _repo(tmp_path)
    rb._commit(repo, {"engine/a.py": "x = 2\n", "tests/pins.json": "{}\n"}, "mixed")
    with pytest.raises(rb.RollbackStop, match="approved bookings"):
        rb.prepare(repo, good, backup_root=tmp_path / "b")


def test_non_ancestor_good_is_refused(tmp_path):
    repo, good = _repo(tmp_path)
    rb.git(repo, "checkout", "-q", "-b", "side")
    side = rb._commit(repo, {"engine/a.py": "x = 9\n"}, "side")
    rb.git(repo, "checkout", "-q", "main")
    rb._commit(repo, {"engine/a.py": "x = 2\n"}, "bad")
    with pytest.raises(rb.RollbackStop, match="not an ancestor"):
        rb.prepare(repo, side, backup_root=tmp_path / "b")


def test_nothing_to_revert_is_refused(tmp_path):
    repo, good = _repo(tmp_path)
    with pytest.raises(rb.RollbackStop, match="nothing to revert"):
        rb.prepare(repo, good, backup_root=tmp_path / "b")


def test_script_never_resets_or_force_pushes():
    src = (ROOT / "scripts" / "rollback_to_good.py").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]  # skip the module docstring
    for banned in ('"reset"', '"push"', "--force-with-lease", '"--force"' + ', "push"', "--no-verify", '"rebase"'):
        assert banned not in body, banned


def test_good_record_round_trip(tmp_path):
    gf = tmp_path / "good.jsonl"
    assert rb.last_good(gf) is None
    rb.record_good("a" * 40, "h" * 16, "2026-11-07T13:00:00-05:00", gf)
    rb.record_good("b" * 40, "h" * 16, "2026-11-07T14:00:00-05:00", gf)
    assert rb.last_good(gf)["revision"] == "b" * 40
