#!/usr/bin/env bash
# Run any command while holding the working-tree lock (flock), so automation never rewrites data/ mid-push.
#   scripts/with_push_lock.sh git commit -am "..."      scripts/with_push_lock.sh git push origin main
# Sets HCE_PUSH_LOCK_HELD=1 so the pre-push hook knows the lock is already held (flock is not re-entrant across processes).
LOCK="${HCE_PUSH_LOCK:-$(git rev-parse --git-common-dir 2>/dev/null || echo /tmp)/hce-push.lock}"
exec flock -w "${HCE_PUSH_LOCK_WAIT:-600}" "$LOCK" env HCE_PUSH_LOCK_HELD=1 "$@"
