# Household Cashflow Engine (Template)

A **privacy-safe** Streamlit app template for projecting household cash flow over ~3 years: recurring bills, paychecks, what-if scenarios, debt paydown analytics, and spending insights.

This repository ships **application code + synthetic demo data only**. It is not anyone’s real household ledger.

## Application vs user data

| Layer | Location | Committed? |
|-------|----------|------------|
| **Application** | `app.py`, `engine/`, `scripts/`, `tests/` | Yes |
| **Synthetic seed** | `seed/`, `sample/fixtures/synthetic/` | Yes (fictional) |
| **Your runtime data** | `data/*.db`, `data/*.csv`, snapshots | **No** (gitignored) |

Never commit real bank CSVs, balances, loan numbers, tax returns, or employer payroll memos.

Demo household (intentionally fake): **Alex Rivera** (primary) · **Jordan Lee** (secondary). Employers: Northstar Tech · BrightStart side-gig.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

First run: choose **Explore Demo** or **Start My Household**. Or pre-build the demo DB with `python scripts/seed_demo.py` (writes `data/cashflow.db` + `sample/demo_bootstrap.db`).

## Explore Demo vs Start My Household

On first launch (empty DB), the app asks you to choose — the modes are hard to confuse:

| Mode | What you get |
|------|----------------|
| **Explore Demo** | Synthetic Alex/Jordan seed, excel-parity overlays, demo debts/scenarios (intentional). |
| **Start My Household** | Clean portable household: generic defaults + optional name / start date / starting balance / as-of / horizon / warning threshold. **No** demo rules, paychecks, debts, bonuses, tax/retirement/rewards seeds, or excel-parity. |

Clean mode is sticky: restart will **not** re-inject demo data or replace your DB from `cloud_bootstrap.db`.

CLI shortcut for demo only:

```bash
python scripts/seed_demo.py
streamlit run app.py
```

Or run the app with no DB and click **Explore Demo** / **Start My Household**.

## Import your own bank CSV (runtime)

Safer workflow on the **Import** page: **preview → Merge or Replace → confirm Replace → auto backup → change report**.
Merge skips duplicate fingerprints (stable bank ID when present). See `HOUSEHOLD_SETUP.md`.

```bash
python scripts/import_bank_csv.py path/to/your_export.csv --preview-only
python scripts/import_bank_csv.py path/to/your_export.csv --mode merge
python scripts/import_bank_csv.py path/to/your_export.csv --mode replace --confirm-replace
```

Files land under `data/` (and backups under `data/backups/`) and stay local. Do not copy them into `seed/` or commit them.

## Backup & privacy

- **Settings → Household backup & restore** writes/reads a whole-household ZIP.
- Where truth lives: `DATA_AND_PRIVACY.md`.

## Project layout

- `app.py` — Streamlit UI
- `engine/` — projection, insights, debt, import helpers
- `seed/` — synthetic recurring rules + paychecks
- `sample/fixtures/synthetic/` — example CSVs/JSON for demos/tests
- `data/` — **runtime only** (empty placeholders in git)
- `scripts/seed_demo.py` — build demo SQLite from synthetic seed
- `tests/` — unit tests against synthetic expectations

## Cloud deploy note

If you deploy to Streamlit Cloud, use **your own** private app URL and secrets. Do not point docs or configs at someone else’s production Cloud URL — replace with yours.

## Privacy

Before any push: scan the tree for personal names, addresses, loan IDs, payroll memos, and real account digits. Keep `data/` gitignored.
