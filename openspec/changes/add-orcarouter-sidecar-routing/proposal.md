## Why

Operators want OrcaRouter as a first-class External Integration in codex-lb: API-key guard, model allowlists, request accounting, Settings, Accounts, and request logs — without routing those requests through Codex, CLIProxyAPI, OpenRouter, OmniRoute, or Ollama.

OrcaRouter exposes a direct OpenAI-compatible Chat Completions API at `https://api.orcarouter.ai/v1`. This change clones the existing OpenRouter HTTP sidecar (aiohttp `GET /models` + `POST /chat/completions`), not the Ollama SDK wrapper and not OmniRoute executors.

## What Changes

- Add dashboard-managed OrcaRouter configuration (disabled by default) with encrypted API key, fresh-install-only seeded prefix `orcarouter/` (strip off), full models, timeouts, cache TTL, and health fields.
- Add an outbound OrcaRouter HTTP client for `/models` and `/chat/completions` with `User-Agent: codex-lb/orcarouter-sidecar`, `HTTP-Referer`, and `X-Title`.
- Insert `orcarouter` into unified sidecar provider order after OpenRouter: `("claude", "openrouter", "orcarouter", "omniroute", "ollama")`.
- Route matching `POST /v1/chat/completions` requests to OrcaRouter. Do not hook `/v1/responses`.
- Forward `orcarouter/auto` unchanged. Bare `auto` is not rewritten by this sidecar (OrcaRouter returns 503 "No available channel").
- Surface an OrcaRouter Settings tab, synthetic account, request-log label, and `/api/orcarouter-sidecar` status/models/test APIs.
- Reject overlapping prefixes/full models with other integrations (including live OmniRoute `orcarouter/`).

## Non-goals

- Do not add OpenCode Zen, OpenCode Free, or any other provider.
- Do not clone Ollama (`import ollama`) or port OmniRoute executors/Responses dispatch.
- Do not seed `openai/`, `google/`, `anthropic/`, or `deepseek/` prefixes.
- Do not invent Orca per-token prices in `pricing.py`. Cost stays null without a pricing row; `-free` still uses `is_known_free_model`.
- Do not edit `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, or hand-write `docs/`. `docs/reference/settings.md` is regenerated from `Settings` by `scripts/generate_settings_reference.py` because the new `CODEX_LB_ORCAROUTER_SIDECAR_*` fields would otherwise leave it drifted.
- Do not restart `codex-lb.service`.

## Capabilities

### New Capabilities

- `orcarouter-sidecar-management`: dashboard persistence, health APIs, synthetic account, request-log labels, and Settings tab.

### Modified Capabilities

- `chat-completions-compat`: OrcaRouter prefix/full-model dispatch on Chat Completions only.
- `model-catalog-compat`: configured OrcaRouter full models in `GET /v1/models` with `owned_by: orcarouter`.
- `api-keys`: allowlist and reservation settlement use the effective client model.
- `frontend-architecture`: OrcaRouter tab and synthetic-account branch.
- `database-migrations`: idempotent OrcaRouter dashboard settings columns.

## Impact

- New OpenRouter-shaped HTTP sidecar files renamed to OrcaRouter.
- Sidecar resolver order, Settings, Accounts, request logs, and frontend fixtures.
- Alembic migration parented on the live head.
