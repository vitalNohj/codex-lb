## Context

Claude quota is already polled into `dashboard_settings.claude_sidecar_quota_state_json` and estimated via `build_claude_usage_estimates` (OAuth remaining % preferred, else token-budget math). Clients need Anthropic’s undocumented `GET /api/oauth/usage` shape with a single pool value, not per-auth dashboard data.

## Goals / Non-Goals

**Goals:**

- Mirror Anthropic path + JSON keys for a pooled Claude estimate.
- API-key auth suitable for programmatic callers.
- Reuse existing estimate aggregate; exclude paused/disabled auths.
- Honor `hide_upstream_quota_from_api_keys` by nulling buckets.

**Non-Goals:**

- Changing dashboard `/api/claude-sidecar/quota`.
- Live Anthropic fetch per request.
- Real `seven_day_opus` / `seven_day_sonnet` / `extra_usage` data.
- Anthropic ratelimit response headers on chat completions.
- Codex/GPT pool (already covered by `/v1/usage`).

## Decisions

1. **Path `GET /api/oauth/usage`** — closest Anthropic mirror; reverse proxy `/codex` strip yields public `/codex/api/oauth/usage`.
2. **Auth `validate_usage_api_key`** — always requires Bearer key (like `/v1/usage`); auth errors use existing proxy envelope, not Anthropic error JSON.
3. **Pool via `build_claude_usage_estimates(...).aggregate`** — already budget-weights OAuth-preferred remaining %; invert to utilization with `100 - remaining`, clamped to `[0, 100]`, one decimal.
4. **Paused exclusion** — drop `disabled` snapshot auths (and matching events/plans) before estimates.
5. **Empty / disabled sidecar** — HTTP 200 with null usage buckets (not 503).
6. **Optional keys** — always present as `null` (`seven_day_opus`, `seven_day_sonnet`, `extra_usage`).
7. **No camelCase** — Anthropic snake_case keys on this route only.

## Risks / Trade-offs

- [Stale poll] → Document that values lag the quota poller interval; do not live-fetch.
- [Clients expect 0–1 utilization] → Emit 0–100 to match Anthropic/Claude Code examples; lock in spec.
- [Hide-upstream nulls look like “no data”] → Same semantic as `/v1/usage` omitting pool; acceptable.
