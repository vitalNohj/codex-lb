# Claude Sidecar Quota Polling Context

## Purpose

`add-claude-sidecar-routing` deliberately deferred Claude quota visibility. CLIProxyAPI 7.1+ now exposes runtime quota state on its Management API. This change polls that endpoint from codex-lb and surfaces the result on the synthetic Claude account, so operators see the same kind of `rate_limited` / `quota_exceeded` signal we already render for Codex accounts.

This change is read-only with respect to CLIProxyAPI: we only call `GET /v0/management/auth-files`. We never POST/DELETE to the Management API and we still never call Anthropic directly.

## Decisions

- The CLIProxyAPI Management API is disabled by default. Operators MUST set `remote-management.secret-key` in `~/.cli-proxy-api/config.yaml` to enable it. `allow-remote` stays false (codex-lb calls 127.0.0.1).
- The Management API key is stored encrypted on `dashboard_settings` using the same pattern as the existing sidecar API key (write-only field, clear flag, `_configured` boolean in responses).
- The poller runs only when `claude_sidecar_enabled=true` AND `claude_sidecar_management_key_encrypted` is set. Default interval is 60 seconds; configurable via dashboard settings.
- The quota snapshot is stored as JSON text on `dashboard_settings.claude_sidecar_quota_state_json` (same pattern as `claude_sidecar_last_health_*`), with `claude_sidecar_quota_checked_at` for staleness.
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

## Status mapping

| Snapshot status | Exceeded auths | Synthetic account `status` |
| --- | --- | --- |
| `healthy` | none | `active` |
| `healthy` | some (not all) | `rate_limited` |
| `healthy` | all | `quota_exceeded` |
| `unauthorized` / `unreachable` / `error` | any | `paused` |

`reset_at_primary` is the earliest non-null `next_recover_at` across exceeded auths.
`last_refresh_at` is the snapshot's `checked_at`.

## Why not call Anthropic directly?

CLIProxyAPI owns Claude OAuth, token refresh, and the `quota` accounting. Adding a second client to Anthropic would re-do its work, risk inconsistent state, and would not respect the same recovery times CLIProxyAPI computes.

## Failure modes the poller handles

- CLIProxyAPI down: HTTP transport failure → snapshot `status="unreachable"`, synthetic account stays `paused`.
- Wrong Management key: HTTP 401/403 → snapshot `status="unauthorized"`, synthetic account stays `paused`.
- Unexpected error parsing the response → snapshot `status="error"` with a human-readable message; loop continues.
- Sidecar disabled or Management key not configured → poller is a no-op (does not touch the snapshot).
