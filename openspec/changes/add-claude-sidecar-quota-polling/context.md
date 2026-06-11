# Claude Sidecar Quota Polling Context

## Purpose

`add-claude-sidecar-routing` deliberately deferred Claude quota visibility. CLIProxyAPI 7.1+ now exposes runtime quota state and per-request token telemetry on its Management API. This change polls hard quota state from `GET /v0/management/auth-files`, drains token telemetry from `GET /v0/management/usage-queue`, and surfaces both hard status and estimated 5-hour / weekly usage on the synthetic Claude account.

This change still never calls Anthropic directly. It uses CLIProxyAPI as the only source for Claude OAuth state and usage telemetry. `GET /v0/management/usage-queue` is a destructive queue read, so codex-lb owns draining it in one background collector; dashboard request handlers never call that endpoint directly.

## Decisions

- The CLIProxyAPI Management API is disabled by default. Operators MUST set `remote-management.secret-key` in `~/.cli-proxy-api/config.yaml` to enable it. `allow-remote` stays false (codex-lb calls 127.0.0.1).
- The Management API key is stored encrypted on `dashboard_settings` using the same pattern as the existing sidecar API key (write-only field, clear flag, `_configured` boolean in responses).
- The poller runs only when `claude_sidecar_enabled=true` AND `claude_sidecar_management_key_encrypted` is set. Default interval is 60 seconds; configurable via dashboard settings.
- The usage collector runs only when `claude_sidecar_enabled=true`, `claude_sidecar_management_key_encrypted` is set, and usage collection is enabled. Default interval is 15 seconds; queue batch size defaults to 100.
- The usage collector drains `/usage-queue`, sanitizes records, stores token counts in `claude_sidecar_usage_events`, and never persists the `api_key` value included in raw CLIProxyAPI records.
- The quota snapshot is stored as JSON text on `dashboard_settings.claude_sidecar_quota_state_json` (same pattern as `claude_sidecar_last_health_*`), with `claude_sidecar_quota_checked_at` for staleness.
- Per-auth plan settings are stored as JSON text on `dashboard_settings.claude_sidecar_auth_plans_json`. Auth entries are keyed primarily by `auth_index`; email/source are fallback display and matching fields when `auth_index` is missing.
- Built-in plan presets (`pro`, `max5`, `max20`) provide editable 5-hour and weekly token budgets. Operators can use `custom` to set both budgets explicitly.
- Estimated usage is calculated from persisted `total_tokens`, not from Anthropic's private subscription accounting. When CLIProxyAPI reports an auth as quota-exceeded, the corresponding estimate is clamped to 0% remaining and hard status wins in the UI.
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

## Estimated usage mapping

The synthetic account uses existing `AccountSummary.usage` fields:

| Field | Meaning for Claude sidecar |
| --- | --- |
| `usage.primary_remaining_percent` | Estimated 5-hour remaining percent across configured Claude auths |
| `usage.secondary_remaining_percent` | Estimated weekly remaining percent across configured Claude auths |
| `window_minutes_primary` | `300` |
| `window_minutes_secondary` | `10080` |
| `reset_at_primary` | Active 5-hour block end, or CLIProxyAPI `next_recover_at` when exceeded |
| `reset_at_secondary` | Active weekly block end when a weekly budget exists |

Percentages are estimated because Anthropic does not expose the subscription quota bucket through a stable public API. The UI labels these values as estimated and keeps hard `rate_limited` / `quota_exceeded` state visible separately.

## Why not call Anthropic directly?

CLIProxyAPI owns Claude OAuth, token refresh, and the `quota` accounting. Adding a second client to Anthropic would re-do its work, risk inconsistent state, and would not respect the same recovery times CLIProxyAPI computes.

## Failure modes the poller handles

- CLIProxyAPI down: HTTP transport failure → snapshot `status="unreachable"`, synthetic account stays `paused`.
- Wrong Management key: HTTP 401/403 → snapshot `status="unauthorized"`, synthetic account stays `paused`.
- Unexpected error parsing the response → snapshot `status="error"` with a human-readable message; loop continues.
- Sidecar disabled or Management key not configured → poller is a no-op (does not touch the snapshot).
- Usage queue unauthorized: collector logs the failure, preserves already collected events, and tries again on the next interval.
- Usage queue down or malformed: collector skips malformed records, does not stop the loop, and preserves the previous estimates.
- Auth has usage but no plan: dashboard shows token totals/per-auth identity but leaves percent fields empty until the operator configures a plan.
