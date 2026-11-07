# Change classes

How edits reach your live data, and which rails apply.

| Class | Examples | Where | Gate | Push |
|-------|----------|-------|------|------|
| **Live / picture** | Bank screenshot balances, pending items, actuals | Live data | `prod_gate` before/after recommended | After the gate is green, then live check |
| **Forecast line** | One bill amount, one approved mitigation | Live data | `prod_gate --compare-snapshot` | After the gate, then live check |
| **Structural what-if** | Bulk rule changes, accepting a scenario | A copy of the database first | `prod_gate` on the copy, review the diff | Only after the household owner agrees |
| **Feature / UI** | New page, layout change | A `staging` branch, previewed locally | Full suite + owner review | Merge to `main` when both agree there are no more findings |

## Rules of thumb
1. Never experiment on the live app. Use a branch or a copy.
2. Commit success is not done. Push, reboot, re-read the live app and confirm the approved figures, then `mark-good`.
3. If live does not match what was approved: stop, fix or roll back, and add a FAILURE_LOG / LEARNINGS entry.
4. Label TEMPLATE vs PRODUCTION clearly on every merge or push request.
