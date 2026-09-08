# Tasks

## 1. Specs

- [x] 1.1 Delta spec for dashboard-sidecar-management (expired OAuth → reauth_required).
- [x] 1.2 `openspec validate show-cliproxy-expired-oauth-as-reauth --strict`.

## 2. Backend

- [x] 2.1 Parse `expired` on `SidecarAuthQuota` from auth-files or the auth JSON `expired` field.
- [x] 2.2 Map past `expired` (plus existing death strings) to `reauth_required` on accounts rows and quota rows.
- [x] 2.3 Unit tests: past expiry badges; future expiry does not; missing expiry unchanged; disk read returns only `expired`; path escape returns none.

## 3. Validation

- [x] 3.1 `uv run pytest tests/unit/test_sidecar_account_summaries.py tests/unit/test_claude_sidecar_quota.py`
