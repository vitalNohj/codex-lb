# Add a per-key "Shared key" toggle

## Why

An owner hands some keys to a friend or client and keeps others for themselves. The per-key `usage_sections` decide what a key sees, but locking a key down means clearing every section by hand, and any later grant (reset credits, pool quota, account emails) can leak by mistake. The owner wants one switch per key that turns every extra off, without removing the capabilities: their own keys must still be able to see account emails and ids, other traffic, quota and reset credits when they choose.

## What Changes

- **`is_shared` on every API key.** A new boolean column (default `false`), accepted by `POST /api/api-keys` and `PATCH /api/api-keys/{id}` as `isShared` and returned on every key. Existing keys stay unshared. Turning the flag on or off never changes the stored `usage_sections`.
- **One rule in `app/modules/api_keys/visibility.py`.** `api_key_is_shared` is the single check. `api_key_visibility` returns no grant at all for a shared key (no upstream limits, account pool, per-account usage, reset credits or quota headers), and the endpoints that only describe the owner's pool refuse a shared key with `403 shared_api_key_not_allowed` (`permission_denied` on the dashboard-envelope fleet routes):
  - `GET` and `POST /v1/reset-credit`
  - `GET /api/fleet/summary`, `GET /api/fleet/observability`, `POST /api/fleet/refresh`
  - `GET /v1/quota-feed`
  - `GET /api/oauth/usage` (pooled Claude utilization)
  - `POST /v1/warmup` and `/v1/warmup/{mode}` (fans out over the owner's accounts and returns their ids)
- **Quota headers.** `_rate_limit_headers_for_request` sends no `x-codex-*` quota headers to a shared key, on every proxied route that emits them.
- **Own budget stays visible.** `/v1/usage` shows a shared key its own usage, limits (cost and tokens included) and `expires_at`, and never mirrors upstream windows. `/api/codex/usage` keeps its credit windows and now also lists the key's own cost, token and model-scoped limits under `additional_rate_limits`, so a cost cap is visible in Codex `/status` (for every key, shared or not).
- **Unshared keys are unchanged.** They follow their `usage_sections` and the global privacy setting exactly as before; the integration tests check each capability on an unshared key with sections enabled.
- **Dashboard.** A "Shared key" checkbox with a "?" help tooltip in the create and edit dialogs. While it is on, the usage-sections picker is disabled with a note; its value is kept and submitted so turning the toggle off restores it. Shared keys get a "Shared" badge in the API key table (Settings) and the APIs list, and a "Visibility" row in the key info. Strings in en, ko and zh-CN.
- **Migration** `20261020_010000_add_api_key_is_shared` adds the column with `server_default false`; the downgrade drops only that column.

## Out of scope

- Budget strictness, lifetime caps, Claude/xAI account scoping.
- `/v1/responses` and `/v1/chat/completions` routing, sticky sessions and account selection.
- `codex.rate_limits` stream events forwarded verbatim on `/backend-api/codex/*` and the Responses WebSocket paths. They carry the upstream account's own quota percentages (no identity) and are part of the Codex CLI protocol; stripping them for shared keys is a follow-up.

## Impact

- Affected specs: `api-keys`.
- Backend: `app/db/models.py`, migration, `app/core/exceptions.py`, `app/core/handlers/exceptions.py`, `app/modules/api_keys/{api,schemas,service,repository,visibility}.py`, `app/modules/fleet/api.py`, `app/modules/quota_feed/api.py`, `app/modules/proxy/api.py`.
- Frontend: `api-key-visibility-fields.tsx` (new), `shared-key-badge.tsx` (new), create and edit dialogs, usage-sections picker (`disabled`), API key table, APIs list item and key info, locales.
