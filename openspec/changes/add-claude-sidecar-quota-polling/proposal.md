## Why

`add-claude-sidecar-routing` deliberately left Claude quota visibility out of scope: codex-lb knows whether CLIProxyAPI is reachable and how many models it lists, but cannot tell whether a Claude OAuth account is currently rate-limited or quota-exhausted. Operators discover the limit only after a request fails. CLIProxyAPI 7.1+ exposes runtime quota state on its Management API (`GET /v0/management/auth-files`) and per-request usage telemetry through `GET /v0/management/usage-queue`, so codex-lb can poll hard quota state, drain token usage records, and surface estimated 5-hour / weekly Claude usage on the synthetic account.

This change overrides the non-goal "Do not add Claude quota scraping" from `add-claude-sidecar-routing` for the specific case of polling CLIProxyAPI's own Management API. Codex-lb still never talks to Anthropic directly.

## What Changes

- Persist an encrypted CLIProxyAPI Management API key, quota poll interval, usage collection controls, and per-auth Claude plan budget settings on `dashboard_settings`, alongside the existing sidecar fields.
- Add a `list_auth_files()` method to the sidecar HTTP client that hits `/v0/management/auth-files` with the Management Bearer key.
- Add a `pop_usage_queue()` method to the sidecar HTTP client that drains `/v0/management/usage-queue` with the Management Bearer key.
- Add a background scheduler that polls auth-files on the configured interval (default 60 seconds) only when the sidecar is enabled AND a Management API key is configured, and stores a normalized quota snapshot + `checked_at` on `dashboard_settings`.
- Add a background collector that drains usage-queue records on a short interval only when the sidecar is enabled AND a Management API key is configured, persists sanitized records in a dedicated table, and never exposes or stores proxy API key secrets.
- Classify the snapshot status as `healthy` / `unauthorized` / `unreachable` / `error` based on the call outcome.
- Calculate estimated 5-hour and weekly Claude usage percentages per auth from persisted usage records and configured per-auth plan budgets (`pro`, `max5`, `max20`, or custom).
- Enrich the synthetic `claude-sidecar` account so its `status`, `reset_at_primary`, `last_refresh_at`, and a new per-auth detail list reflect the latest snapshot (no auths exceeded → `active`; some exceeded → `rate_limited`; all exceeded → `quota_exceeded`; earliest non-null `next_recover_at` populates `reset_at_primary`).
- Populate the synthetic `claude-sidecar` account's standard `usage` and window fields with estimated 5-hour and weekly remaining percentages when plan budgets are configured.
- Include the synthetic account in `GET /api/dashboard/overview` (appended after sorting, never affecting Codex aggregates).
- Add a dashboard endpoint `GET /api/claude-sidecar/quota` exposing the latest snapshot.
- Add Settings UI for entering and clearing the Management API key plus tweaking the poll interval.
- Render hard quota status and clearly labeled estimated usage bars on the Accounts list/detail and on the Dashboard home card.

## Non-goals

- Multiple synthetic accounts; one synthetic row aggregates all Claude auth files, with per-auth detail in the account detail panel.
- Driving warmups, pause/resume, or any destructive lifecycle actions for the synthetic account.
- Calling Anthropic directly from codex-lb or reading any state outside CLIProxyAPI's Management API.
- Managing the CLIProxyAPI process lifecycle, cookies, or auth files. Codex-lb only performs read-style Management API calls; `usage-queue` reads are destructive queue drains owned by codex-lb and are never triggered by dashboard request handlers.
- Claiming the estimated percentages are official Anthropic quota readings. They are estimates derived from local CLIProxyAPI telemetry and configured plan budgets.

## Capabilities

### Modified Capabilities

- `dashboard-sidecar-management`: encrypted Management API key persistence; quota poll interval; usage queue collection; per-auth Claude plan budget settings; background quota poller; estimated usage enrichment for the synthetic account; synthetic account included in dashboard overview; new quota endpoint.

## Impact

- New DB columns and Alembic migration on `dashboard_settings`.
- New `claude_sidecar_usage_events` persistence for sanitized CLIProxyAPI usage queue records.
- New sidecar Management API client method in `app/core/clients/claude_sidecar.py`.
- New quota snapshot module `app/modules/claude_sidecar/quota.py`.
- New usage queue parser, collector, repository, and estimation module under `app/modules/claude_sidecar/`.
- New scheduler `app/modules/claude_sidecar/quota_poller.py` wired into `app/main.py` lifespan.
- Settings repository/service/schemas/API additions for the Management key + poll interval.
- Synthetic-account builder extracted to `app/modules/accounts/sidecar_summary.py` and enriched with quota state plus estimated usage.
- Dashboard overview service appends the synthetic account.
- Frontend: `AccountSummarySchema` additions, synthetic-card branch on `AccountCard`, list/detail estimated quota rows, settings page Management key controls, per-auth plan controls, and quota status hook.
