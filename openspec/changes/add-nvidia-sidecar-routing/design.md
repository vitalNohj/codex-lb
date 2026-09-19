## Overview

NVIDIA is a first-class HTTP sidecar cloned from the OpenRouter aiohttp client. Configuration lives on `DashboardSettings`. Routing uses the unified sidecar resolver. Dashboard status/models/test live under `/api/nvidia-sidecar`. Chat Completions is the only proxy surface.

## Locked names

| Surface | Value |
| --- | --- |
| UI tab / request-log label / synthetic display name | `NVIDIA` (never the word "sidecar") |
| Resolver provider | `nvidia` |
| Request-log source | `nvidia_sidecar` |
| `/v1/models` `owned_by` | `nvidia` |
| Synthetic `account_id` | `nvidia-sidecar` |
| Dashboard API | `/api/nvidia-sidecar` |
| DB/API prefix | `nvidia_sidecar_*` |
| Frontend camelCase | `nvidiaSidecar*` |
| Default base URL | `https://integrate.api.nvidia.com/v1` |
| Seeded prefix | none (`[]`), matching OpenRouter |
| User-Agent | `codex-lb/nvidia-sidecar` |

`SIDECAR_PROVIDER_ORDER` becomes `("claude", "openrouter", "nvidia", "orcarouter", "omniroute", "ollama", "opencode_go")`.

## Client

Clone `app/core/clients/openrouter_sidecar.py`. Outbound calls:

- `GET {base}/models`
- `POST {base}/chat/completions`

Bearer `nvapi-…` is required for outbound calls. Missing key: skip network; dashboard status is `missing_api_key`.

Headers on every request: `Accept`, `Content-Type`, `User-Agent`, plus `Authorization` when a key is stored. Do not copy OrcaRouter's `HTTP-Referer`, `X-Title`, or `X-OrcaRouter-Include-Cost`.

If `/models` returns OpenRouter-shaped `pricing` objects, parse them into the runtime pricing registry under `provider="nvidia"`. NVIDIA NIM listings typically omit prices; unknown models log `cost_usd = null`. Do not add invented rows to `DEFAULT_PRICING_MODELS`.

## Routing

Full-model exact match beats prefixes. API-key checks, reservations, and request logs use the effective client model. The resolver wire model is forwarded to NVIDIA.

DeepSeek V4 `reasoning_content` repair stays on the chat path (same helper as OpenRouter, `provider="nvidia"`). Effort override is a true override: always force the operator value when set.

Chat Completions only. `/v1/responses` is not dispatched to NVIDIA. Unique prefix/full-model validation includes NVIDIA.

## Persistence

Idempotent Alembic column adds cloned from the OpenCode Go dashboard-settings migration, parented on the live Alembic head. Prefix JSON server default is `[]`. `enabled` defaults false. Include `nvidia_sidecar_default_reasoning_effort`. Downgrade drops only the new columns.

## UI

One new tab in the existing External Integrations card, after OpenRouter and before OrcaRouter. Enable toggle above the callout. Prefixes, full models, discovered models, timeouts, effort override. Autosave via `SidecarIntegrationCard`. External links open in a new tab with `rel="noopener noreferrer"`. Docs link: https://build.nvidia.com/.

`synthetic-account-detail.tsx` must have an explicit `nvidia` branch. Claude pause/quota UI stays on the Claude allowlist. NVIDIA matches OpenRouter for generic sidecar status rows (hide Quota/Models).

The dashboard account-type filter must expose an `nvidia` key after OpenRouter and before OrcaRouter.
