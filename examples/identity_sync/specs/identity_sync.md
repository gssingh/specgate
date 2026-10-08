# Identity provisioning sync

The sync compares HR records (the source of truth for who works here and
which roles they should have) with accounts in the identity system, and
plans the changes needed to bring accounts in line. It only plans; applying
the changes is someone else's job.

Some role pairs must never be held by one person (separation of duties),
for example `payments_submitter` and `payments_approver`.

## SYNC-001: New hire gets an account
- Given an active HR record for "e100" with roles "engineer"
- And no account exists for "e100"
- When the sync runs
- Then an account is created for "e100" with roles "engineer"

## SYNC-002: Termination disables the account
- Given a terminated HR record for "e200"
- And an enabled account exists for "e200"
- When the sync runs
- Then the account for "e200" is disabled

## SYNC-003: Rehire re-enables the existing account
- Given an active HR record for "e300" with roles "analyst"
- And a disabled account exists for "e300" with roles "engineer"
- When the sync runs
- Then the account for "e300" is re-enabled
- And its roles are set to "analyst"
- But no new account is created for "e300"

## SYNC-004: Role change updates the account
- Given an active HR record for "e400" with roles "manager"
- And an enabled account exists for "e400" with roles "engineer"
- When the sync runs
- Then the roles for "e400" are set to "manager"

## SYNC-005: Conflicting roles are flagged, not applied
- Given an active HR record for "e500" with roles "payments_submitter" and "payments_approver"
- And no account exists for "e500"
- When the sync runs
- Then "e500" is flagged for review naming both conflicting roles
- And no account is created for "e500"

## SYNC-006: Sync is idempotent
- Given an active HR record for "e600" with roles "engineer"
- And an enabled account exists for "e600" with roles "engineer"
- When the sync runs
- Then no changes are planned
