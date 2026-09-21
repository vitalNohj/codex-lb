## Why

Operators need OpenAI-compatible Chat Completions endpoints that are not a first-class sidecar (Vast.ai, vLLM, LM Studio, and similar). NVIDIA already has a dedicated tab. Vast and anything else should be a named tab created from a `+` control on External Integrations, not another cloned sidecar.

## What Changes

- Persist a JSON list of generic OpenAI-compatible endpoints on dashboard settings (`openai_compat_endpoints_json`, default `[]`).
- Add a `+` control on the External Integrations tab row that creates a named tab (Name + Base URL).
- Each endpoint uses an OpenRouter-shaped card: enable, base URL, optional API key, prefixes, full models, Discovered Models, timeouts, true effort override, test connection, remove.
- Route matching `POST /v1/chat/completions` to `openai_compat:{uuid}`. Do not hook `/v1/responses`.
- Surface one synthetic account per endpoint (`provider: openai_compat`, display name = operator name) and one dashboard filter key `openai_compat`.
- Include generic endpoints in prefix/full-model uniqueness.

## Non-goals

- Do not add a dedicated Vast.ai sidecar or pre-seed a Vast endpoint.
- Do not clone NVIDIA/OpenRouter into N first-class integrations.
- Do not add generic endpoints to Free Model Discovery.
- Do not invent per-token prices. Cost stays null unless the upstream `/models` listing or usage object supplies a parseable price. Do not treat echoed `usage.cost` as per-request billed spend.
- Do not edit `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, or hand-write `docs/`.
- Do not restart `codex-lb.service`.

## Capabilities

### New Capabilities

- `openai-compat-endpoints`: dashboard list persistence, `+` tabs, health APIs, synthetic accounts, request-log labels.

### Modified Capabilities

- `chat-completions-compat`: generic OpenAI-compat prefix/full-model dispatch on Chat Completions only.
- `model-catalog-compat`: configured full models in `GET /v1/models` with `owned_by: openai_compat`.
- `api-keys`: allowlist and reservation settlement use the effective client model.
- `frontend-architecture`: `+` tab control, per-endpoint cards, synthetic-account branch, dashboard filter key.
- `database-migrations`: idempotent `openai_compat_endpoints_json` column.

## Impact

- One JSON settings column, one generic HTTP client, one dispatch module, Settings tab row `+`, Accounts synthetics, request logs.
- First-class sidecars (NVIDIA, OpenRouter, and the rest) stay unchanged.
