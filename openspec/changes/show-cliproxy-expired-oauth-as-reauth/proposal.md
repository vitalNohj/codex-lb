# Show CLIProxyAPI expired OAuth as re-auth required

## Why

Claude sidecar cards only showed **Re-auth required** when CLIProxyAPI's management auth-files poll already said `unauthorized` / `invalid_grant` / `authentication_error`. A dead Max OAuth (refresh `invalid_grant`, access token `expired` in the past) stayed `active` on the dashboard because CLIProxyAPI still listed the file as a candidate. Operators had no re-auth label even though the account could not continue without a login.

## What Changes

- Treat a Claude auth whose OAuth access-token `expired` timestamp is in the past as `reauth_required`.
- Keep the existing status-message and `unavailable`+`unauthorized` mappings.
- Read `expired` from the auth-files list when present; otherwise read only that field from the auth JSON at the list entry's `path` (under the CLIProxyAPI auth dir). Never return or log token fields.
- Apply the same mapped status on accounts/dashboard sidecar rows and on the Claude quota endpoint.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `dashboard-sidecar-management`: per-auth Claude sidecar status MUST be `reauth_required` whenever that credential cannot continue without operator re-login

## Impact

- Code: `app/modules/claude_sidecar/quota.py`, `app/modules/accounts/sidecar_summary.py`, `app/modules/claude_sidecar/service.py`
- Tests: `tests/unit/test_sidecar_account_summaries.py`, `tests/unit/test_claude_sidecar_quota.py`
- No frontend change: `ClaudeAuthCard` already renders the badge when `auth.status === "reauth_required"`
- No migration, no restart required (quota poller picks up `expired` on the next poll)
