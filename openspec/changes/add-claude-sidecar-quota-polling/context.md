# Claude Sidecar Quota Polling Context

## Purpose

`add-claude-sidecar-routing` deliberately deferred Claude quota visibility. CLIProxyAPI 7.1+ now exposes runtime quota state and per-request token telemetry on its Management API. This change polls hard quota state from `GET /v0/management/auth-files`, optionally reads the local CLIProxyAPI Claude OAuth token file path from that metadata to query Anthropic's OAuth usage endpoint, drains token telemetry from `GET /v0/management/usage-queue`, and surfaces hard status plus 5-hour / weekly usage on the synthetic Claude account.

The source order is: hard quota status from CLIProxyAPI auth-files, official OAuth usage from Anthropic when a readable local Claude token is available, and usage-queue-derived estimates when OAuth usage is unavailable. `GET /v0/management/usage-queue` is a destructive queue read, so codex-lb owns draining it in one background collector; dashboard request handlers never call that endpoint directly.

## Decisions

- The CLIProxyAPI Management API is disabled by default. Operators MUST set `remote-management.secret-key` in `~/.cli-proxy-api/config.yaml` to enable it. `allow-remote` stays false (codex-lb calls 127.0.0.1).
- The Management API key is stored encrypted on `dashboard_settings` using the same pattern as the existing sidecar API key (write-only field, clear flag, `_configured` boolean in responses).
- The poller runs only when `claude_sidecar_enabled=true` AND `claude_sidecar_management_key_encrypted` is set. Default interval is 60 seconds; configurable via dashboard settings.
- The usage collector runs only when `claude_sidecar_enabled=true`, `claude_sidecar_management_key_encrypted` is set, and usage collection is enabled. Default interval is 15 seconds; queue batch size defaults to 100.
- The usage collector drains `/usage-queue`, sanitizes records, stores token counts in `claude_sidecar_usage_events`, and never persists the `api_key` value included in raw CLIProxyAPI records.
- The quota snapshot is stored as JSON text on `dashboard_settings.claude_sidecar_quota_state_json` (same pattern as `claude_sidecar_last_health_*`), with `claude_sidecar_quota_checked_at` for staleness.
- During quota polling, codex-lb reads only local Claude auth-file paths returned by CLIProxyAPI Management API metadata. If an auth file contains a top-level `access_token`, codex-lb calls `https://api.anthropic.com/api/oauth/usage` with `anthropic-beta: oauth-2025-04-20`, stores normalized remaining percentages and reset timestamps in the quota snapshot, and never stores the token.
- Per-auth plan settings are stored as JSON text on `dashboard_settings.claude_sidecar_auth_plans_json`. Auth entries are keyed primarily by `auth_index`; email/source are fallback display and matching fields when `auth_index` is missing.
- Built-in plan presets (`pro`, `max5`, `max20`) provide editable 5-hour and weekly token budgets. Operators can use `custom` to set both budgets explicitly.
- OAuth usage percentages are treated as official remaining percentages when present. Otherwise, estimated usage is calculated from persisted `total_tokens`, not from Anthropic's private subscription accounting. When CLIProxyAPI reports an auth as quota-exceeded, the corresponding 5-hour remaining value is clamped to 0% and hard status wins in the UI.
- The synthetic account is enriched (not duplicated). One synthetic row aggregates all Claude auth files; per-auth detail lives in the account detail panel.
- The dashboard overview appends the synthetic account AFTER sorting Codex accounts so it always lands last and never affects Codex aggregates.

## CLIProxyAPI Management API enablement

Add to `~/.cli-proxy-api/config.yaml`:

```yaml
remote-management:
  secret-key: "<generated-with-openssl-rand-hex-24>"
```

Then `systemctl --user restart cli-proxy-api.service`. Verify with:

```bash
curl -H "Authorization: Bearer <key>" http://127.0.0.1:8317/v0/management/auth-files
```

Wrong or missing key returns HTTP 401.

## Auth-files response shape (live)

```jsonc
{
  "files": [
    {
      "id": "claude-<email>.json",
      "name": "claude-<email>.json",
      "provider": "claude",
      "type": "claude",
      "account_type": "oauth",
      "auth_index": "<hex>",
      "email": "<email>",
      "label": "<email>",
      "disabled": false,
      "unavailable": false,
      "status": "active",
      "status_message": "",
      "success": 0,
      "failed": 0,
      "recent_requests": [{ "time": "21:10-21:20", "success": 0, "failed": 0 }],
      "modtime": "2026-06-10T21:21:55.198308875Z",
      "updated_at": "2026-06-10T22:26:13.233038158Z"
      // omitted when not rate-limited:
      // "quota": { "exceeded": true, "next_recover_at": "2026-06-10T23:30:00Z" }
      // "model_states": { "claude-sonnet-4-5-20250929": { "exceeded": true, "next_recover_at": "..." } }
    }
  ]
}
```

The `quota` and `model_states` objects are `omitempty` on the CLIProxyAPI side: they appear only when an account/model is currently exceeded. The parser tolerates both shapes.

## Usage-queue response shape

`GET /v0/management/usage-queue?count=100` returns an array and removes those records from CLIProxyAPI's queue:

```jsonc
[
  {
    "timestamp": "2026-05-05T12:00:00Z",
    "latency_ms": 1234,
    "source": "person@example.com",
    "auth_index": "0",
    "tokens": {
      "input_tokens": 10,
      "output_tokens": 20,
      "reasoning_tokens": 0,
      "cached_tokens": 0,
      "total_tokens": 30
    },
    "failed": false,
    "provider": "claude",
    "model": "claude-sonnet-4-5",
    "alias": "claude",
    "endpoint": "POST /v1/chat/completions",
    "auth_type": "oauth",
    "api_key": "sk-...",
    "request_id": "req_..."
  }
]
```

Codex-lb persists the timestamp, safe identifiers, token counts, model metadata, failure flag, latency, and request ID. It does not persist `api_key`.

## Status mapping

| Snapshot status | Exceeded auths | Synthetic account `status` |
| --- | --- | --- |
| `healthy` | none | `active` |
| `healthy` | some (not all) | `rate_limited` |
| `healthy` | all | `quota_exceeded` |
| `unauthorized` / `unreachable` / `error` | any | `paused` |

`reset_at_primary` is the earliest non-null `next_recover_at` across exceeded auths.
`last_refresh_at` is the snapshot's `checked_at`.

## Usage mapping

The synthetic account uses existing `AccountSummary.usage` fields:

| Field | Meaning for Claude sidecar |
| --- | --- |
| `usage.primary_remaining_percent` | 5-hour remaining percent across Claude auths, from OAuth usage when available or local estimates otherwise |
| `usage.secondary_remaining_percent` | Weekly remaining percent across Claude auths, from OAuth usage when available or local estimates otherwise |
| `window_minutes_primary` | `300` |
| `window_minutes_secondary` | `10080` |
| `reset_at_primary` | Active 5-hour block end, or CLIProxyAPI `next_recover_at` when exceeded |
| `reset_at_secondary` | Active weekly block end when a weekly budget exists |

The UI labels values by source: `OAuth` when Anthropic's OAuth usage endpoint supplied the percentages, `Estimated` when values come from local token telemetry and configured budgets, and `Unavailable` when neither source has percentages yet. Hard `rate_limited` / `quota_exceeded` state remains visible separately.

## Why read local OAuth usage?

CLIProxyAPI owns Claude OAuth and token refresh, but its usage queue is local telemetry, not Anthropic's subscription bucket. Anthropic's OAuth usage endpoint returns the actual five-hour and seven-day utilization buckets. Codex-lb reads only the local auth-file path that CLIProxyAPI reports, uses the access token transiently during the quota poll, stores only normalized percentages/reset timestamps, and falls back to usage-queue estimates if the endpoint is unavailable.

## Failure modes the poller handles

- CLIProxyAPI down: HTTP transport failure → snapshot `status="unreachable"`, synthetic account stays `paused`.
- Wrong Management key: HTTP 401/403 → snapshot `status="unauthorized"`, synthetic account stays `paused`.
- Unexpected error parsing the response → snapshot `status="error"` with a human-readable message; loop continues.
- Sidecar disabled or Management key not configured → poller is a no-op (does not touch the snapshot).
- Usage queue unauthorized: collector logs the failure, preserves already collected events, and tries again on the next interval.
- Usage queue down or malformed: collector skips malformed records, does not stop the loop, and preserves the previous estimates.
- OAuth usage unavailable: quota poller preserves hard auth-files status and leaves OAuth usage fields empty; local estimates can still populate percentages when plan budgets exist.
- Auth has usage but no plan and no OAuth usage: dashboard shows token totals/per-auth identity but leaves percent fields empty until the operator configures a plan or OAuth usage becomes available.
