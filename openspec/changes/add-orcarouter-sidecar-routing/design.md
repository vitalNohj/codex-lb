## Overview

OrcaRouter is a first-class HTTP sidecar cloned from the OpenRouter aiohttp client. Configuration lives on `DashboardSettings`. Routing uses the unified sidecar resolver. Dashboard status/models/test live under `/api/orcarouter-sidecar`. Chat Completions is the only proxy surface.

## Locked names

| Surface | Value |
| --- | --- |
| UI tab / request-log label / synthetic display name | `OrcaRouter` (never the word "sidecar") |
| Resolver provider | `orcarouter` |
| Request-log source | `orcarouter_sidecar` |
| `/v1/models` `owned_by` | `orcarouter` |
| Synthetic `account_id` | `orcarouter-sidecar` |
| Dashboard API | `/api/orcarouter-sidecar` |
| DB/API prefix | `orcarouter_sidecar_*` |
| Frontend camelCase | `orcarouterSidecar*` |
| Default base URL | `https://api.orcarouter.ai/v1` |
| Seeded prefix (fresh install only) | `[{"prefix":"orcarouter/","strip":false}]` |
| User-Agent | `codex-lb/orcarouter-sidecar` |
| Referer | `https://github.com/vitalNohj/codex-lb` |
| X-Title | `codex-lb` |

`SIDECAR_PROVIDER_ORDER` becomes `("claude", "openrouter", "orcarouter", "omniroute", "ollama")`.

## Client

Clone `app/core/clients/openrouter_sidecar.py`. Outbound calls:

- `GET {base}/models`
- `POST {base}/chat/completions`

Bearer `sk-orca-…` is required. Missing key: skip network; dashboard status is `missing_api_key`.

Headers on every request: `User-Agent`, `HTTP-Referer`, `X-Title`, plus `Authorization` when a key is stored.

If `/models` returns OpenRouter-shaped `pricing` objects, parse them into the runtime pricing registry under `provider="orcarouter"`. OrcaRouter and OpenRouter both list ids such as `deepseek/deepseek-chat` at different prices, so a provider-qualified lookup must return that provider's own price and an OrcaRouter refresh must not redefine a shared id in the unqualified overlay that the provider-less OmniRoute and Ollama callers read; `app/core/usage/runtime_pricing.py` owns that rule. A `/models` response is that source's current catalogue snapshot and never a statement that a model is gone everywhere (the client raises instead of recording on transport, HTTP, or response-shape failure). It replaces that source's key space keyed on the ids the response actually listed, not on the subset that produced a usable price: an id the source stops listing is dropped from that source and from the unqualified overlay unless another source currently lists it, while an id the source still lists but prices in an unparseable shape keeps its last successfully parsed value. An id no source currently lists therefore has no runtime reference price rather than a retired one, and an upstream pricing-shape change cannot wipe a source's prices. Do not add invented rows to `DEFAULT_PRICING_MODELS`. Unknown models log `cost_usd = null`. Models ending in `-free` still go through `is_known_free_model`.

## Routing

Full-model exact match beats prefixes. Seeded `orcarouter/` has strip off, so `orcarouter/auto` is the wire model. Operator-pinned vendor IDs are full models so they beat OpenRouter prefixes.

API-key checks, reservations, and request logs use the effective client model. The resolver wire model is forwarded unstripped for the seeded prefix.

DeepSeek V4 `reasoning_content` repair stays on the chat path (same helper as OpenRouter, `provider="orcarouter"`). Effort override is a true override: always force the operator value when set.

Chat Completions only. `/v1/responses` is not dispatched to OrcaRouter. Unique prefix/full-model validation includes OrcaRouter; a colliding OmniRoute `orcarouter/` prefix is rejected on save. Settings callout tells the operator to remove that OmniRoute prefix before enabling.

## Persistence

Idempotent Alembic column adds cloned from the Ollama dashboard-settings migration, parented on the live head `20260818_000000_backfill_claude_opus_5_sonnet_5_costs`. Prefix JSON server default is `[]`, so existing rows are never backfilled with an active `orcarouter/` prefix that would collide with a deployment where OmniRoute already owns it; the seeded `[{"prefix":"orcarouter/","strip":false}]` is applied only on a fresh install (`_seed_fresh_install_prefixes`). `enabled` defaults false. Downgrade drops only the new columns.

## UI

One new tab in the existing External Integrations card. Enable toggle above the callout. Prefixes, full models, discovered models, timeouts, effort override. Autosave via `SidecarIntegrationCard`. External links open in a new tab with `rel="noopener noreferrer"`.

`synthetic-account-detail.tsx` must have an explicit `orcarouter` branch. Claude pause/quota UI is picked by an allowlist on the Claude provider, never by excluding the known non-Claude ones; `specs/frontend-architecture/spec.md` owns that rule, the absent-provider case, and the account-type filter key.
