# Household setup (portable)

## First run

1. `pip install -r requirements.txt` then `streamlit run app.py`
2. Choose **Explore Demo** (synthetic Alex/Jordan) or **Start My Household** (clean, empty portable defaults).
3. Clean mode never re-injects demo data on restart.

## Import bank CSV (safer workflow)

On the **Import** page (or CLI):

1. **Preview** — date range, row counts, categorized/uncategorized, overlap with existing `bank_csv`, duplicate fingerprints, short-history warning.
2. Choose **Merge** or **Replace**.
3. **Replace** requires an explicit confirm; a timestamped household ZIP backup is written first under `data/backups/`.
4. After import, review the **change report** (inserted / skipped dupes / cleared).

Fingerprints (Merge):

- Prefer a stable bank **Transaction ID** when the CSV has one.
- Otherwise: `date + amount + normalized memo/label + source`.

```bash
python scripts/import_bank_csv.py statement.csv --preview-only
python scripts/import_bank_csv.py statement.csv --mode merge
python scripts/import_bank_csv.py statement.csv --mode replace --confirm-replace
```

## Backup & restore

**Settings → Household backup & restore** (or API in `engine/household_backup.py`):

- ZIP includes the SQLite DB (settings, rules, planned, actuals, scenarios, merchant maps) plus sidecars when present (debts, live checking, net worth, retirement, tax, rewards, …).
- Restore validates the ZIP, auto-backs up the current household, then replaces.

See `DATA_AND_PRIVACY.md` for where truth lives.
