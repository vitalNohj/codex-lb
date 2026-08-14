## Why

Dashboard Claude auth cards map CLIProxyAPI auth-death shapes onto `reauth_required` so the existing StatusBadge works. The current fallback treats any `unavailable` auth with `status` in `{error, unauthorized}` as reauth — including transient failures like `status_message="context canceled"` when the OAuth token is still valid. That false positive sends operators toward unnecessary re-login.

## What Changes

- Tighten Claude sidecar → dashboard `reauth_required` mapping to require stronger auth-death evidence.
- Keep message-based signals (`authentication_error`, `re-authenticate`, `invalid_grant`, oauth+expired).
- Keep `unavailable` + `status=unauthorized` as the only status fallback (stronger than generic `error`).
- Stop mapping generic `status=error` (e.g. `context canceled`) to `reauth_required`; preserve the raw status for the existing badge path.
- No UI/visual changes: same StatusBadge labels and card chrome; only which rows qualify as reauth.

## Capabilities

### New Capabilities

- (none)

### Modified Capabilities

- `dashboard-sidecar-management`: Claude per-auth dashboard status MUST map to `reauth_required` only on auth-death evidence, not on generic unavailable/error rows.

## Impact

- Backend: `app/modules/accounts/sidecar_summary.py` (`_looks_like_reauth`)
- Tests: `tests/unit/test_sidecar_account_summaries.py`
- No frontend, API schema, or badge copy changes
