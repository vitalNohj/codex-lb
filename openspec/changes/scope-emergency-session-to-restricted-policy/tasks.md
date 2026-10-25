## 1. Backend

- [x] 1.1 `DashboardAuthService.verify_totp`: emit `break_glass_login` only when `user.is_break_glass and policy_is_tightened(local_login_policy)`, reading the policy on the success path.
- [x] 1.2 `DashboardAuthService.describe_session`: `break_glass_session` also requires `policy_is_tightened(settings.local_login_policy)` from the settings the method already reads.

## 2. Tests

- [x] 2.1 Unit (`test_dashboard_auth_password_service.py`): for `enabled`, `admins_only` and `break_glass_only`, TOTP sign-in of the designated account writes `login_success`, and the critical row and session flag appear only under a restricted policy. The same live cookie is relabelled as the policy changes.
- [x] 2.2 Integration (`test_local_login_policy_break_glass.py`): the always-two-factor test asserts the label and the critical row per policy. The unenrolled-designation test runs under `enabled` and `admins_only`. A new test relabels one live session across `break_glass_only` → `enabled` → `admins_only` with no extra audit row.
- [x] 2.3 Frontend (`app-header.test.tsx`): the pill follows the refreshed session for each policy and disappears from a live tab when a refresh reports the policy loosened.

## 3. Docs and verification

- [x] 3.1 `docs/sso.md`: the pill and the critical row are described as belonging to a restricted policy.
- [x] 3.2 `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, the dashboard-auth unit suites and the break-glass integration suite. Frontend: `vitest` on the header and auth suites, `lint`, `typecheck`. `openspec validate scope-emergency-session-to-restricted-policy --strict`.
