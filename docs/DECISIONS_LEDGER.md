# Decisions ledger (one list of household rules)

Every rule your household decides goes here once, with the test that enforces it, so nobody asks the same question
twice. `scripts/rules_drift_check.py` reads this table (run by the pre-push hook).

Status: `Active` (built and tested), `Pending` (decided, not built yet), `Retired` (kept for history).
Before asking the household anything, check this ledger and LEARNINGS first.

The rows below are **EXAMPLE DATA**: generic engine rules that ship with the template. Add your own rows (R-10 and up)
with your own values; never put account numbers or passwords here.

| Id | Rule | Status | Enforcing test |
|----|------|--------|----------------|
| R-01 | EXAMPLE: no real household value (account digits, emails, phones) is ever committed | Active | `tests/test_privacy_guard.py::test_generic_layer_blocks` |
| R-02 | EXAMPLE: a planned item and an actual for the same money are never counted twice | Active | `tests/test_safety_rails.py::test_prod_gate_blocks_double_count` |
| R-03 | EXAMPLE: a change that adds a red month needs a stated reason before it ships | Active | `tests/test_safety_rails.py::test_prod_gate_compare_flags_new_red_month` |
| R-04 | EXAMPLE: rollback never erases an approved booking and never rewrites history | Active | `tests/test_rollback_to_good.py::test_rehearsal_on_synthetic_repo_passes_every_check` |
| R-05 | EXAMPLE: every blocked push has a FAILURE_LOG entry | Active | `tests/test_failure_log.py::test_every_entry_is_well_formed` |
| R-06 | EXAMPLE: pictures and real databases never go into git | Active | `tests/test_safety_rails.py::test_rules_ledger_is_clean` |
| R-07 | EXAMPLE (your household): a bank screenshot always wins over an older bank feed figure | Pending | (add a test when built) |
