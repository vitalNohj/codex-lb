# NVIDIA sidecar routing

## Purpose

Let operators send NVIDIA NIM Chat Completions through `https://integrate.api.nvidia.com/v1` while codex-lb keeps API-key auth, allowlists, reservations, Settings, Accounts, Discovered Models, and request logs.

## Why clone OpenRouter

OpenRouter is already an aiohttp OpenAI-compatible sidecar (`GET /models`, `POST /chat/completions`, SSE relay, reservation settlement, DeepSeek V4 repair, effort override, Discovered Models browser). NVIDIA NIM is the same shape. Ollama is the wrong template (official SDK). A generic multi-endpoint list was considered and rejected: the operator asked for a dedicated NVIDIA tab.

## What is NVIDIA-specific

- Default base URL `https://integrate.api.nvidia.com/v1`
- Display name / slug / docs / `nvapi-…` key placeholder
- No Free Model Discovery membership
- No catalog prices expected, so `cost_usd` stays null unless NVIDIA starts returning them

Everything else matches OpenRouter: enable, key, prefixes, full models, Discovered Models, effort override, timeouts, health, test connection, routing, synthetic account, HTTP request logs.

## Prefixes

Do not seed a prefix. OpenRouter also starts with an empty prefix list. The operator pins full models from Discovered Models (for example `z-ai/glm-5.3`) or adds a prefix such as `nvidia/` with strip on from the UI.

## API keys

Create keys at https://build.nvidia.com/settings. Keys start with `nvapi-`. Missing key: no outbound HTTP; status `missing_api_key`. Do not commit or log the key.
