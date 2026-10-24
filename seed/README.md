# Synthetic seed data (demo household)

This folder holds **fictional** starter rules for the Household Cashflow Engine template.

| File | Purpose |
|------|---------|
| `rules.json` | Recurring expense/transfer rules (demo amounts) |
| `paychecks.json` | Alex & Jordan income by year (synthetic) |
| `starting_balance.json` | Demo checking EOD seed |
| `categories.json` | Lightweight category catalog |
| `dashboard_sample.json` | Optional sample month-end curve |

**Household names:** Alex Rivera (primary) · Jordan Lee (secondary). Employers: Northstar Tech · BrightStart academy side-gig.

Do **not** commit real bank CSVs, balances, or loan numbers into this folder.
Replace these JSON files (or re-import via the app) with your own data at runtime under `data/` (gitignored).
