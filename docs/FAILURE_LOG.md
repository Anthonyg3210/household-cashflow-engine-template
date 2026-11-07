# Failure Log: push-gate / suite failures

Every failed pre-push gate (privacy guard, pytest, prod_gate or rules drift) that blocks a push gets ONE entry here
**before** the fix is pushed. Goal: see which causes cost the most time and kill them at the source.
Guard: `tests/test_failure_log.py`. Summary: `python scripts/failure_summary.py` (`--trend` for the weekly review).

## Entry format (strict; the guard parses it)

```
### FL-NNN — YYYY-MM-DD — <short title>
- **Date:** YYYY-MM-DD
- **Failing test:** `tests/test_x.py::test_y` (comma-separated list; `prod_gate` for the gate)
- **Root cause:** one or two sentences, no blame
- **Cause class:** one of stale-pin | stale-generated-data | engine-bug | process | flaky | environment
- **Corrective action:** what was changed (and what prevents the next one)
- **Time lost:** 1h20m  (forms: 6h, 1h20m, 45m)
- **LEARNINGS:** exact start of the matching `## ` heading in docs/LEARNINGS.md (or `none`)
```

Newest entries go at the bottom. Never delete history; add a dated follow-up if an entry turns out wrong.

## Entries

### FL-001 — 2026-01-05 — EXAMPLE DATA: a test's temporary git commit landed in the pushing repo
- **Date:** 2026-01-05
- **Failing test:** `tests/test_rollback_to_good.py::test_rehearsal_on_synthetic_repo_passes_every_check`
- **Root cause:** EXAMPLE DATA (replace with your first real entry). Git exports GIT_DIR to hooks, so a test that made its own temporary repo wrote into the repo being pushed.
- **Cause class:** environment
- **Corrective action:** The pre-push hook now unsets every GIT_* variable before running tests, and test helpers strip GIT_* from their environment.
- **Time lost:** 30m
- **LEARNINGS:** none
