## Why

Programs that call Claude through the proxy need Anthropic-shaped pool utilization (`GET /api/oauth/usage`) as a single opaque percentage across Claude accounts. The dashboard `GET /api/claude-sidecar/quota` response is operator-oriented (per-auth, remaining %, session auth) and is not usable as an Anthropic-compatible client contract.

## What Changes

- Add `GET /api/oauth/usage` authenticated with a Bearer API key (always required, same pattern as `/v1/usage`).
- Return Anthropic OAuth usage JSON: `five_hour` / `seven_day` buckets with `utilization` (used percent 0–100) and `resets_at`, plus `seven_day_opus`, `seven_day_sonnet`, and `extra_usage` as `null`.
- Compute one pooled estimate across non-paused Claude auths from the existing polled snapshot + usage estimates (no live Anthropic call on the request path).
- When `hide_upstream_quota_from_api_keys` is enabled, return the same Anthropic keys with usage buckets set to `null`.
- Leave dashboard `GET /api/claude-sidecar/quota` unchanged.

## Capabilities

### New Capabilities

- `anthropic-oauth-usage`: Client-facing Anthropic-shaped Claude pool usage endpoint.

### Modified Capabilities

<!-- none -->

## Impact

- `app/modules/claude_sidecar/` (mapper + service assembly)
- Proxy usage routing (`GET /api/oauth/usage`)
- Unit tests for mapper, pool exclusion, hide-upstream, and auth
- OpenSpec change artifacts under `openspec/changes/add-anthropic-oauth-usage-endpoint/`
