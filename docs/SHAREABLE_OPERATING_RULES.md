# Shareable operating rules

Generic process rules for any household using this template. Examples in this repo stay synthetic. Do not paste a real ledger, balances, names, merchants, or card snapshots here.

## Already in the template

- Bank CSV import is preview, then merge or a confirmed replace, with a household backup before replace. Import does not wipe recurring rules or scenarios.
- `set_live_checking` writes the JSON sidecar and the database mirrors together. Do not update the balance in only one of those places.
- Cash cushion is the dollars required to lift the deepest trough in a red streak to the clear-to level (default zero).
- Recurring rules may set `off_months` so a bill does not fire in months that are intentionally off.
- `get_settings()` returns projection keys only.

## Rules

1. **A higher cushion is worse.** Cushion is the set-aside implied by the deepest trough. More cushion means more cash is required to stay non-negative. Do not treat a higher cushion, or red months disappearing, as an improvement unless a real inflow or timing change explains it.

2. **Import leaves the projection anchor alone.** Do not overwrite `start_balance`, start date, or end date from a bank CSV when they are already set. The import report echoes the stored start balance. It must not claim a hardcoded demo balance. The synthetic demo default is only a seed.

3. **Do not read live checking from `get_settings()`.** That helper drops `live_checking_*` keys even when they are stored on `settings`. Use `data/live_checking.json` or `engine.live_checking`.

4. **Relabeling is not a balance change.** Fixing a category or memo does not change cash totals unless the amount itself is wrong.

5. **One source updates one account.** A checking screenshot or paste does not authorize creating or changing a different account.

6. **Locked day-of-month beats a lender label.** For cash timing, the cash-due day is the household locked day-of-month. A loan-detail "next payment" date is a period label, not the checking debit day, unless the household re-locks the day-of-month. Name the source when citing a due day.

7. **Count card pending once.** If pending charges are already reserved in available credit, amount owed is limit minus available. That is the same as current balance plus pending, counted once. Do not add pending a second time.

8. **A deploy is not done at push.** After publishing a hosted app, re-read the live app and confirm the figures match what you signed off. The local process is not the hosted process.

## What stays out

Real bank exports, balances, loan identifiers, payroll memos, card snapshots, and household names. Incident notes and decision logs for a live household belong in that household's private repo, not in this template.
