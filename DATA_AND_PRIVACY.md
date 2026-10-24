# Data & privacy (sketch)

## Where truth lives

| Kind of truth | Location | Notes |
|---------------|----------|--------|
| Projection settings (start balance, horizon) | SQLite `settings` in `data/cashflow.db` | Source of truth for the cash twin |
| Recurring rules / paychecks | `recurring_rules` | Demo seed only if Explore Demo |
| Planned one-offs | `planned_items` | |
| Bank / card history | `actuals` (`source=bank_csv` or `rewards_card`) | Imported; not committed |
| Scenarios | `scenarios` | |
| Merchant → category maps | `merchant_maps` + optional `data/merchant_map.json` | Learned patterns |
| Debts | `data/debts.json` | Sidecar |
| Live checking snapshot | `data/live_checking.json` (+ settings mirrors) | Sidecar |
| Net worth cards | `data/net_worth_snapshot.json` | Optional |
| Retirement / tax / rewards | `data/retirement_*.json`, `tax_*.json`, `rewards_cards.json`, … | Optional modules |
| Household backups | `data/backups/household_backup_*.zip` | Local only |

## Privacy rules

- **Never commit** real CSVs, balances, loan IDs, tax returns, or payroll memos.
- `data/*.db`, most `data/*.json`, and backups are **gitignored**.
- This template ships **synthetic** seed under `seed/` and `sample/fixtures/synthetic/` only.
- Clean household init does **not** copy demo finances into your DB.

## Backup hygiene

- Prefer the in-app / `create_household_backup` ZIP before Replace import or Restore.
- Treat backup ZIPs like the live DB: private, local, not uploaded to public repos.

## License

**License:** MIT (see `LICENSE`) — free to use, copy, modify, and fork.

## Privacy guard (blocks real values)

`scripts/privacy_guard.py` scans every tracked file (SQLite files are dumped to text) and, with `--history`, every
blob in every commit. Any hit fails the check. A hit prints the file and a masked hint, never the value.

- **Generic layer** (always on, also in CI): emails other than example.*, phone numbers, SSN-like numbers,
  account-like digit runs, and card "ending in" / "last 4" mentions.
- **Private layer** (run by the maintainer before every push): `--private-repo PATH [--extra-terms FILE]` derives
  the real household's identifiers, names, cities and exact amounts from the private repo at run time. That list is
  never written into this repo.

```bash
python scripts/privacy_guard.py --history
python scripts/privacy_guard.py --history --private-repo ../private-repo --extra-terms ../private-terms.json
```

All people, employers, lenders, servicers, merchants, balances and dates in this repo are fictitious.
