"""The privacy guard blocks real household values from this public template (scripts/privacy_guard.py).

Generic layer: always on. Private layer: derived at run time from a private repo's data (set HCE_PRIVATE_REPO to run
it here); its values are never stored in this repo. Fixtures below use made-up values only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import privacy_guard as g  # noqa: E402


def _repo(tmp_path: Path, files: dict[str, str], name="repo") -> Path:
    r = tmp_path / name
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x"], check=True)
    return r


def _fake_private(tmp_path: Path) -> Path:
    """A made-up 'private repo' (surname Zubrowski) with the shapes the real one has."""
    p = tmp_path / "zubrowski-cashflow-twin"
    (p / "data").mkdir(parents=True)
    (p / "data" / "debts.json").write_text(json.dumps({"debts": [{"name": "Loan", "account_number": "QX7712345",
                                                                  "current_balance": 43210.77, "rate": 6.125}]}))
    (p / "data" / "tax_profile.json").write_text(json.dumps({"current_year_stub": {"employer": "Quillfeather Dynamics"}}))
    (p / "data" / "income.csv").write_text("date,source,gross,net,type\n2026-01-01,Bartholomew biweekly,,3333.17,pay\n")
    (p / "data" / "rewards_card_ledger.json").write_text(json.dumps({"rows": [{"description": "TACO HUT ZEPHYRVILLE FL"}]}))
    return p


# built at run time so this file holds no literal pattern the guard would flag
_BAD = ["write to jane.doe" + "@" + "gmail.com", "call (321) 555" + "-0147", "ssn 123-45" + "-6789",
        "acct 0044177" + "82219", "card ending" + " in 4417"]


@pytest.mark.parametrize("text", _BAD)
def test_generic_layer_blocks(tmp_path, text):
    r = _repo(tmp_path, {"notes.md": text})
    assert g.run(r, None, False)


@pytest.mark.parametrize("text", ["see user@example.com", "on 2026-09-12 ending 2029-09-12", "id DEMO00000000001",
                                  "total $1,234.56", "version 20261023"])
def test_generic_layer_allows_fictitious_and_technical(tmp_path, text):
    r = _repo(tmp_path, {"notes.md": text})
    assert g.run(r, None, False) == []


@pytest.mark.parametrize("text", ["account QX7712345", "balance 43,210.77", "rate 6.125", "pay 3333.17",
                                  "Bartholomew pays", "Quillfeather office", "dinner in Zephyrville", "the Zubrowski house"])
def test_private_layer_blocks_values_derived_from_the_private_repo(tmp_path, text):
    priv = _fake_private(tmp_path)
    r = _repo(tmp_path, {"app.py": f"# {text}\n"})
    hits = g.run(r, priv, False)
    assert hits and all("private" in h for h in hits)


def test_hits_never_print_the_value(tmp_path):
    priv = _fake_private(tmp_path)
    r = _repo(tmp_path, {"a.md": "QX7712345 and Bartholomew"})
    out = "\n".join(g.run(r, priv, False))
    assert "QX7712345" not in out and "Bartholomew" not in out and "…" in out


def test_history_scan_catches_a_value_removed_later(tmp_path):
    priv = _fake_private(tmp_path)
    r = _repo(tmp_path, {"a.md": "balance 43,210.77"})
    (r / "a.md").write_text("balance 1,000.00")
    subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "y"], check=True)
    assert g.run(r, priv, False) == []
    assert any(h.startswith("history") for h in g.run(r, priv, True))


def test_sqlite_files_are_scanned(tmp_path):
    import sqlite3
    priv = _fake_private(tmp_path)
    r = tmp_path / "r"; r.mkdir(); subprocess.run(["git", "init", "-q", str(r)], check=True)
    con = sqlite3.connect(r / "demo.db"); con.execute("create table t(x)"); con.execute("insert into t values ('Bartholomew')"); con.commit(); con.close()
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    assert g.run(r, priv, False)


def test_extra_terms_file_is_honoured(tmp_path):
    r = _repo(tmp_path, {"a.md": "we bank at Glimmerstone"})
    extra = tmp_path / "extra.json"; extra.write_text(json.dumps({"terms": ["Glimmerstone"], "numbers": ["1979"]}))
    assert g.run(r, None, False, extra=extra)


def test_this_template_is_clean_generic_layer_with_history():
    assert g.run(ROOT, None, True) == []


@pytest.mark.skipif(not os.environ.get("HCE_PRIVATE_REPO"), reason="set HCE_PRIVATE_REPO to run the private layer")
def test_this_template_is_clean_private_layer_with_history():
    extra = os.environ.get("HCE_PRIVATE_TERMS")
    assert g.run(ROOT, Path(os.environ["HCE_PRIVATE_REPO"]), True, extra=Path(extra) if extra else None) == []
