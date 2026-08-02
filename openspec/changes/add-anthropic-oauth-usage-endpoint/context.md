# Anthropic OAuth usage endpoint (pooled Claude)

## Purpose

Expose `GET /api/oauth/usage` as an Anthropic-compatible client contract for a single pooled Claude utilization estimate.

## Rationale

Claude Code and tooling expect Anthropic’s undocumented oauth usage JSON (`five_hour` / `seven_day` with `utilization` used %). Coders calling through the proxy need that shape without learning per-account dashboard APIs.

## Examples

```http
GET /api/oauth/usage
Authorization: Bearer <api-key>
```

```json
{
  "five_hour": { "utilization": 33.0, "resets_at": "2026-04-11T07:00:00+00:00" },
  "seven_day": { "utilization": 13.0, "resets_at": "2026-04-17T00:59:59+00:00" },
  "seven_day_opus": null,
  "seven_day_sonnet": null,
  "extra_usage": null
}
```

## Ops

Values come from the Claude quota poller snapshot + local estimates; they lag the poll interval. Paused auths are excluded. `hide_upstream_quota_from_api_keys` nulls the buckets.
