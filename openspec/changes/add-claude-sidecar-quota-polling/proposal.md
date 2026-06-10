## Why

`add-claude-sidecar-routing` deliberately left Claude quota visibility out of scope: codex-lb knows whether CLIProxyAPI is reachable and how many models it lists, but cannot tell whether a Claude OAuth account is currently rate-limited or quota-exhausted. Operators discover the limit only after a request fails. CLIProxyAPI 7.1+ exposes the runtime quota state on its Management API (`GET /v0/management/auth-files`), so codex-lb can poll it and surface the same kind of "rate-limited" / "quota-exceeded" signal we already render for Codex accounts.

This change overrides the non-goal "Do not add Claude quota scraping" from `add-claude-sidecar-routing` for the specific case of polling CLIProxyAPI's own Management API. Codex-lb still never talks to Anthropic directly.

## What Changes

- Persist an encrypted CLIProxyAPI Management API key and a quota poll interval on `dashboard_settings`, alongside the existing sidecar fields.
- Add a `list_auth_files()` method to the sidecar HTTP client that hits `/v0/management/auth-files` with the Management Bearer key.
- Add a background scheduler that polls auth-files on the configured interval (default 60 seconds) only when the sidecar is enabled AND a Management API key is configured, and stores a normalized quota snapshot + `checked_at` on `dashboard_settings`.
- Classify the snapshot status as `healthy` / `unauthorized` / `unreachable` / `error` based on the call outcome.
- Enrich the synthetic `claude-sidecar` account so its `status`, `reset_at_primary`, `last_refresh_at`, and a new per-auth detail list reflect the latest snapshot (no auths exceeded → `active`; some exceeded → `rate_limited`; all exceeded → `quota_exceeded`; earliest non-null `next_recover_at` populates `reset_at_primary`).
- Include the synthetic account in `GET /api/dashboard/overview` (appended after sorting, never affecting Codex aggregates).
- Add a dashboard endpoint `GET /api/claude-sidecar/quota` exposing the latest snapshot.
- Add Settings UI for entering and clearing the Management API key plus tweaking the poll interval.
- Render quota information on the Accounts list/detail and on the Dashboard home card (new synthetic branch) without quota bars, warmup, or credit fields.

## Non-goals

- Percent-based quota bars for Claude (CLIProxyAPI exposes only exceeded-or-not + recovery time).
- Multiple synthetic accounts; one synthetic row aggregates all Claude auth files, with per-auth detail in the account detail panel.
- Driving warmups, pause/resume, or any destructive lifecycle actions for the synthetic account.
- Calling Anthropic directly from codex-lb or reading any state outside CLIProxyAPI's Management API.
- Managing the CLIProxyAPI process lifecycle, cookies, or auth files (we only read `auth-files`; we do not POST/DELETE).

## Capabilities

### Modified Capabilities

- `dashboard-sidecar-management`: encrypted Management API key persistence; quota poll interval; background quota poller; quota-enriched synthetic account; synthetic account included in dashboard overview; new quota endpoint.

## Impact

- New DB columns and Alembic migration on `dashboard_settings`.
- New sidecar Management API client method in `app/core/clients/claude_sidecar.py`.
- New quota snapshot module `app/modules/claude_sidecar/quota.py`.
- New scheduler `app/modules/claude_sidecar/quota_poller.py` wired into `app/main.py` lifespan.
- Settings repository/service/schemas/API additions for the Management key + poll interval.
- Synthetic-account builder extracted to `app/modules/accounts/sidecar_summary.py` and enriched with quota state.
- Dashboard overview service appends the synthetic account.
- Frontend: `AccountSummarySchema` additions, synthetic-card branch on `AccountCard`, list/detail quota rows, settings page Management key controls and quota status hook.
