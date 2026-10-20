# Close what API key holders can see

## Why

A codex-lb API key can be handed to someone who should only use the proxy. Several API-key endpoints showed that holder more than the key's own usage, and the existing knobs (per-key `usage_sections` and the global `hide_upstream_quota_from_api_keys`) did not stop it:

- `GET /v1/reset-credit` listed the email and id of every Codex account in the key's pool, and `POST /v1/reset-credit` let the key spend the owner's ChatGPT reset credits. No section or setting gated either.
- `GET /api/fleet/summary` always listed each account's email and display name, including when usage was hidden.
- `POST /api/fleet/refresh` let any key trigger upstream usage refreshes.
- `GET /v1/quota-feed` ignored both knobs. It returned every CLIProxyAPI credential and its quota to every key, and labelled Codex rows with the router account id, which embeds the ChatGPT account id.
- Three Responses dispatch paths (OpenCode Go, OmniRoute and the chat-provider path used by Claude and other sidecars) sent the pool-wide `x-codex-*` quota headers without the privacy check every other path applies.
- `GET /v1/usage` did not return the key's own expiry.

## What Changes

- **One visibility rule.** `app/modules/api_keys/visibility.py` decides what a key may see, and every endpoint below uses it. `upstream_limits` shows pool-wide upstream quota (aggregate Codex windows, CLIProxyAPI credential quota). `account_pool_usage` shows the key's Codex account pool. Per-account Codex usage and account identity need both. The global privacy setting hides all of it from API keys.
- **New `reset_credits` usage section.** `GET` and `POST /v1/reset-credit` answer `403` unless the key has it. New keys are created without it. Existing keys also lose it by default: the migration `20261020_000000_add_api_key_reset_credits_section` holds a single `GRANT_RESET_CREDITS_TO_EXISTING_KEYS` flag, `False` as shipped; set to `True`, it adds the section to every existing key so they keep today's access. The admin can enable the section per key in the dashboard create and edit dialogs.
- **Fleet.** `/api/fleet/summary` lists no accounts without `account_pool_usage` (or with the privacy setting on), and omits `email` and `displayName` when the key cannot see per-account usage. `/api/fleet/refresh` answers `403` under the same rule as fleet usage, before any refresh work.
- **Quota feed.** For an API key, Codex rows need per-account usage visibility and CLIProxyAPI rows need `upstream_limits`; the privacy setting hides both. `accountKey` is an opaque per-key HMAC of the router id, keyed with the deployment's encryption key, so it is stable for that key and different for every other key. The dashboard admin keeps the full feed with router ids.
- **Headers.** The three Responses dispatchers read quota headers through `_rate_limit_headers_for_request`, like every other path.
- **`/v1/usage`.** Returns `expires_at`. `limits` mirrors upstream windows only when the key may see them (already the case; now covered by tests).

## Out of scope

- A per-key "shared holder" flag (PR B), budget enforcement and lifetime caps, and Claude/xAI account scoping. Follow-ups.
- Normal `/v1/responses` and `/v1/chat/completions` routing, sticky sessions and account selection are unchanged. Dashboard (admin session) views are unchanged.

## Capabilities

### New capability: `quota-feed` (the existing `/v1/quota-feed` gets its first spec entries)

## Impact

- Affected specs: `api-keys`, `fleet-summary`, `quota-feed`.
- Backend: `app/modules/api_keys/visibility.py` (new), `app/modules/api_keys/service.py`, `app/modules/fleet/{api,mappers,schemas}.py`, `app/modules/quota_feed/{api,service}.py`, `app/modules/proxy/{api,schemas}.py`, migration `20261020_000000_add_api_key_reset_credits_section`.
- Frontend: the API key usage-sections picker gains "Reset credits" and a hint explaining what each section reveals.
- Operators: keys that used `/v1/reset-credit` stop working until an admin enables "Reset credits" on them. Fleet and quota-feed consumers that relied on emails, raw account ids, or seeing data with sections turned off see less.
