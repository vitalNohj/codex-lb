## Overview

Generic OpenAI-compatible endpoints are a dashboard-managed JSON list, not a first-class sidecar. Each list item is an aiohttp Chat Completions client (`GET {base}/models`, `POST {base}/chat/completions`) with its own tab, routing identity, and synthetic account.

## Locked names

| Surface | Value |
| --- | --- |
| Settings JSON column | `openai_compat_endpoints_json` |
| Frontend / API list field | `openaiCompatEndpoints` |
| Resolver provider | `openai_compat:{uuid}` |
| Request-log source | `openai_compat:{uuid}` |
| `/v1/models` `owned_by` fallback | `openai_compat` |
| Synthetic `account_id` | `openai-compat-{uuid}` |
| Synthetic `provider` | `openai_compat` |
| Dashboard filter key | `openai_compat` |
| Dashboard API | `/api/openai-compat/{endpoint_id}/status\|models\|test` |
| User-Agent | `codex-lb/openai-compat` |
| Default list | `[]` |

`SIDECAR_PROVIDER_ORDER` is unchanged. Providers not in that tuple rank last (`len(ORDER)`), so generic endpoints lose ties to first-class integrations. Uniqueness still forbids shared prefixes/full models.

`is_capability_enabled("openai_compat:{uuid}")` stays true because unknown capabilities are not in `DISABLED_PRODUCT_CAPABILITIES`.

## Endpoint record

Each stored object:

- `id` (UUID string, client or server assigned)
- `name` (tab label and synthetic display name; unique case-insensitive)
- `enabled` (default false)
- `base_url` (required http(s); operator supplies Vast as `https://openai.vast.ai/<ENDPOINT_NAME>/v1` so the client posts `{base}/chat/completions`)
- `api_key_encrypted` (optional; Fernet bytes stored as base64 inside JSON)
- `model_prefixes`, `full_models`, timeouts, cache TTL, `default_reasoning_effort`
- health fields (`last_health_*`) preserved on operator save; test-connection writes them without bumping settings version

Cap: 32 endpoints.

## Client

Clone the OpenRouter/NVIDIA aiohttp client, parameterized per endpoint. API key is optional: no key means no `Authorization` header (vLLM/LM Studio). A stored key is sent as `Bearer`. Missing key does **not** block `/models` or chat.

Headers: `Accept`, `Content-Type`, `User-Agent`, plus `Authorization` when a key is stored. Do not copy OrcaRouter referer/cost headers.

If `/models` returns OpenRouter-shaped `pricing` objects, parse them into the runtime pricing registry under `provider="openai_compat:{uuid}"`. Unknown models log `cost_usd = null`. Do not add invented rows to `DEFAULT_PRICING_MODELS`. Do not treat echoed `usage.cost` as `upstream_billed`.

## Routing

Full-model exact match beats prefixes. API-key checks, reservations, and request logs use the effective client model. The resolver wire model is forwarded.

DeepSeek V4 `reasoning_content` repair runs on the chat path (`provider="openai_compat:{uuid}"`). Effort override is a true override: always force the operator value when set.

Chat Completions only. `/v1/responses` is not dispatched. Chat dispatch must match `openai_compat:` **before** the OmniRoute fallback assert.

## Persistence

Idempotent Alembic column `openai_compat_endpoints_json` TEXT default `'[]'`, parented on the NVIDIA settings migration. Downgrade drops only that column.

## UI

`+` button on the External Integrations tab row (not itself a tab). Dialog: Name + Base URL. Hint copy may mention Vast `https://openai.vast.ai/<ENDPOINT_NAME>/v1`. New tab appears after first-class tabs, in list order.

Each tab is an OpenRouter-shaped `SidecarIntegrationCard` plus Remove. Enable toggle above the callout. Autosave the whole list. External links, if any, use `rel="noopener noreferrer"`.

Uniqueness collection includes every endpoint's prefixes and full models, using the operator name as the owner label.

Synthetic account UI has an explicit `openai_compat` branch (not Claude). Hide Quota/Models like OpenRouter/NVIDIA. Effort override patches that endpoint in the JSON list. Configure hash: `#openai-compat-{uuid}`.

Dashboard account-type filter exposes `openai_compat` after existing keys, default visible, hydrating old stored prefs without resetting other toggles.
