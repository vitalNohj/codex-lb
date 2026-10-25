## Why

The migration that introduced dashboard accounts backfills `is_break_glass` on the compat `admin` account, so on every upgraded install that account is designated. Because the emergency label and the critical audit row followed the designation alone, every sign-in of that account carried the amber **Emergency session** pill in the header. Once it enrolled two-factor, every sign-in also wrote a `break_glass_login` row at critical severity. That happened even though `local_login_policy` was `enabled` and password sign-in was the ordinary way in for every account. The result is a label that is always on and a critical severity that fires on routine sign-ins. Both stop meaning anything, which is the outcome `local-login-policy-and-break-glass` already tried to avoid for accounts without a second factor.

A break-glass sign-in is an emergency only when the account uses the door that a restricted policy keeps open for it. Under `enabled`, that door is open to everyone.

## What Changes

- `verify_totp` writes `break_glass_login` (critical) only when the account is designated **and** `local_login_policy` is `admins_only` or `break_glass_only` at the moment the second factor is verified. Under `enabled`, only the ordinary `login_success` row is written.
- The session response's `break_glass_session` is true only when the cookie carries the emergency marker **and** the current policy is restricted. The policy is read for each session response, not frozen in the cookie. Loosening the policy removes the pill from existing sessions, and tightening it adds the pill, the next time the client reads its session. The login-policy card already refreshes the session after a save, so the tab that changes the policy updates immediately.
- The `bg` cookie marker is unchanged. It still records the designation at mint time, so cookies already issued keep decoding, and the payload version does not change.
- Unchanged: the designation, the qualification rules, the `assert_break_glass_remains` guards, the migration, the always-two-factor rule for a designated account that holds a secret (under every policy), and the header component.

## Capabilities

### Modified Capabilities

- `admin-auth`: the critical break-glass audit row and the session response's emergency flag now also depend on `local_login_policy` being restricted.

## Impact

- `app/modules/dashboard_auth/service.py`: `describe_session` and `verify_totp`, plus one import. `app/modules/dashboard_auth/schemas.py`: a field comment.
- Tests: `tests/unit/test_dashboard_auth_password_service.py` and `tests/integration/test_local_login_policy_break_glass.py` cover both policy states, and `frontend/src/components/layout/app-header.test.tsx` checks that the pill follows the refreshed session.
- Docs: `docs/sso.md`.
- No schema change, no migration, no new setting, no wire field added or removed.
