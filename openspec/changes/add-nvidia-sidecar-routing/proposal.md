## Why

Operators want NVIDIA NIM models (including the hosted trial catalog at `https://integrate.api.nvidia.com/v1`) reachable through codex-lb's API-key guard, allowlists, request accounting, Settings, Accounts, and request logs without routing those requests through Codex, CLIProxyAPI, OpenRouter, OrcaRouter, OmniRoute, or Ollama.

NVIDIA NIM is an OpenAI-compatible Chat Completions API. This change clones the existing OpenRouter HTTP sidecar (aiohttp `GET /models` + `POST /chat/completions`) into a first-class NVIDIA External Integrations tab. It does not clone the Ollama SDK wrapper and does not add a generic multi-endpoint "+" list.

## What Changes

- Add dashboard-managed NVIDIA configuration (disabled by default) with prefilled base URL `https://integrate.api.nvidia.com/v1`, encrypted API key, prefixes, full models, timeouts, cache TTL, health fields, and reasoning-effort override.
- Add an outbound NVIDIA HTTP client cloned from OpenRouter for `/models` and `/chat/completions`.
- Insert `nvidia` into unified sidecar provider order after OpenRouter: `("claude", "openrouter", "nvidia", "orcarouter", "omniroute", "ollama", "opencode_go")`.
- Route matching `POST /v1/chat/completions` requests to NVIDIA. Do not hook `/v1/responses`.
- Surface a NVIDIA Settings tab (same card as OpenRouter, including Discovered Models), a synthetic account, request-log label `NVIDIA`, and `/api/nvidia-sidecar` status/models/test APIs.
- Reject overlapping prefixes/full models with other integrations.

## Non-goals

- Do not add a generic OpenAI-compat "+" multi-endpoint list.
- Do not clone Ollama (`import ollama`) or port OmniRoute executors/Responses dispatch.
- Do not add NVIDIA to Free Model Discovery. That panel probes OpenRouter/OrcaRouter ids with `free` in the name; NVIDIA's trial quota is not that catalog marker.
- Do not invent NVIDIA per-token prices in `pricing.py`. Cost stays null unless the NVIDIA `/models` listing or usage object supplies a parseable price.
- Do not edit `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, or hand-write `docs/`.
- Do not restart `codex-lb.service`.

## Capabilities

### New Capabilities

- `nvidia-sidecar-management`: dashboard persistence, health APIs, synthetic account, request-log labels, and Settings tab.

### Modified Capabilities

- `chat-completions-compat`: NVIDIA prefix/full-model dispatch on Chat Completions only.
- `model-catalog-compat`: configured NVIDIA full models in `GET /v1/models` with `owned_by: nvidia`.
- `api-keys`: allowlist and reservation settlement use the effective client model.
- `frontend-architecture`: NVIDIA tab and synthetic-account branch.
- `database-migrations`: idempotent NVIDIA dashboard settings columns.

## Impact

- New OpenRouter-shaped HTTP sidecar files renamed to NVIDIA.
- Sidecar resolver order, Settings, Accounts, request logs, and frontend fixtures.
- Alembic migration parented on the live head.
