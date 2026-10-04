# Shareable operating rules

Generic process rules for any household using this template. Examples in this repo stay synthetic. Do not paste a real ledger, balances, names, merchants, or card snapshots here.

## Already in the template

- Bank CSV import is preview, then merge or a confirmed replace, with a household backup before replace. Import does not wipe recurring rules or scenarios.
- `set_live_checking` writes the JSON sidecar and the database mirrors together. Do not update the balance in only one of those places.
- Cash cushion is the dollars required to lift the deepest trough in a red streak to the clear-to level (default zero).
- Recurring rules may set `off_months` so a bill does not fire in months that are intentionally off.
- `get_settings()` returns projection keys only.
- A posted bank actual replaces that month's single forecast line, including when the post day differs from the rule day. The actual's amount and classification are what remain.
- Variable override categories use a planning average until that month has a posted actual, then that month uses the bank amount.
- Card amount owed prefers limit minus available, which already counts pending once.
- Same-visit card pending (pre-tip, tip-final, stale pending) collapses to one line.
- An observed or unverified feed is dropped before it can enter the verified forecast.

## Rules

1. **A higher cushion is worse.** Cushion is the set-aside implied by the deepest trough. More cushion means more cash is required to stay non-negative. Do not treat a higher cushion, or red months disappearing, as an improvement unless a real inflow or timing change explains it.

2. **Import leaves the projection anchor alone.** Do not overwrite `start_balance`, start date, or end date from a bank CSV when they are already set. The import report echoes the stored start balance. It must not claim a hardcoded demo balance. The synthetic demo default is only a seed.

3. **Do not read live checking from `get_settings()`.** That helper drops `live_checking_*` keys even when they are stored on `settings`. Use `data/live_checking.json` or `engine.live_checking`.

4. **Relabeling is not a balance change.** Fixing a category or memo does not change cash totals unless the amount itself is wrong. Reclassification must not write a new amount.

5. **One source updates one account.** A checking export or screenshot does not authorize creating or changing a different account. A card export writes card actuals only and must not clear checking actuals. Do not invent posted card actuals from a pending header or from a row that is still pending or an authorization. A pending header is not a posted ledger.

6. **Lock the post day. A lender "next payment" label does not move it.** The cash-due day is the day the bill actually posts (the locked day-of-month, or the usual posted day when nothing is locked). A loan-detail "next payment" date is a period label, not the checking debit day, unless the household re-locks the day-of-month. Name the source when citing a due day. Do not invent a due day from the lender label.

7. **Variable bills: average, then the posted month.** Until a bank actual arrives, plan the variable bill from its average. When that month's actual posts, that month's itemization becomes the bank amount. Do not leave the old forecast figure beside it.

8. **A forecast line that hits the bank is replaced for that month.** When a forecasted checking item posts at a different amount, update that month's itemization to the actual amount and classification. Updating the available balance alone is not enough. One monthly line is replaced even if the post day differs. Several lines in the same month (a biweekly pay, for example) are replaced only on the matching date.

9. **Count card pending once.** If pending charges are already reserved in available credit, amount owed is limit minus available. That is the same obligation as posted balance plus pending, counted once. Do not add pending a second time, and do not prefer a current-balance label that omits pending when limit and available are known. Do not stack a pre-tip authorization, the tip-final amount, and a stale pending copy for the same visit. Keep one line, and do not sum those stages.

10. **A deploy is not done at push.** After publishing a hosted app, re-read the live app and confirm the figures match what you signed off. The local process is not the hosted process. Commit success is not the last step.

11. **Do not promote an observed or unverified feed into the verified forecast.** Pics and statements (and a bank export the household accepts as a statement) are the source for verified money. An observed feed may be watched beside the forecast. It must not silently become decision-grade cash, runway, or cushion math.

## What stays out

Real bank exports, balances, loan identifiers, payroll memos, card snapshots, and household names. Incident notes and decision logs for a live household belong in that household's private repo, not in this template.
