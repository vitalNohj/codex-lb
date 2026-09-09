# Tasks

## 1. Specs

- [x] 1.1 Delta spec for dashboard-sidecar-management (expired OAuth → reauth_required).
- [x] 1.2 `openspec validate show-cliproxy-expired-oauth-as-reauth --strict`.

## 2. Backend

- [x] 2.1 Parse `expired` on `SidecarAuthQuota` from auth-files or the auth JSON `expired` field.
- [x] 2.2 Map explicit auth-failure evidence to `reauth_required` on accounts rows and quota rows. Access-token expiry age is not a signal at any lapse duration.
- [x] 2.3 Unit tests: lapsed expiry never badges (minutes through 90 days); future expiry does not; missing expiry unchanged; disk read returns only `expired`; path escape returns none.
- [x] 2.4 Do not badge quota-exceeded or operator-paused credentials, and treat an `unauthorized` / `invalid_grant` status message as re-auth even while the token is unexpired.
- [x] 2.5 Match `unauthorized` exactly after trim/casefold, never as a substring, so a transient upstream message containing the word does not badge.

## 3. Validation

- [x] 3.1 `pytest tests/unit/test_sidecar_account_summaries.py tests/unit/test_claude_sidecar_quota.py tests/unit/test_claude_sidecar_quota_poller.py tests/integration/test_claude_sidecar_dashboard_api.py` - 99 passed, run under an OS deny-all-network parent policy with a sanitized environment.
- [x] 3.2 Quota-endpoint integration coverage for the in-process HTTP path: lapsed expiry stays `active`, an exact `unauthorized` message badges, a transient message containing `unauthorized` does not, and pause/quota keep their labels.
- [ ] 3.3 Browser/UI verification of the rendered badge - still outstanding, needs a separately reviewed loopback fixture.
