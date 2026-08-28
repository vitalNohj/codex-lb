# OrcaRouter sidecar routing

## Purpose

Let operators send `orcarouter/…` Chat Completions through OrcaRouter while codex-lb keeps API-key auth, allowlists, reservations, Settings, Accounts, and request logs.

## Why clone OpenRouter

OpenRouter is already an aiohttp OpenAI-compatible sidecar (`GET /models`, `POST /chat/completions`, SSE relay, reservation settlement, DeepSeek V4 repair, effort override). OrcaRouter is the same shape at `https://api.orcarouter.ai/v1`. Ollama is the wrong template (official SDK). OmniRoute executors and Responses dispatch are out of scope.

## Prefix and auto

Seed only `orcarouter/` with strip off. `orcarouter/auto` must be forwarded as `orcarouter/auto`. Sending bare `auto` to OrcaRouter returns 503 `No available channel`; this sidecar does not strip the seeded prefix to prevent that.

Do not seed `openai/`, `google/`, `anthropic/`, or `deepseek/`. Those collide with OpenRouter. Pin Orca vendor IDs as full models so exact match wins.

## OmniRoute collision

Some deployments already give OmniRoute the `orcarouter/` prefix. Uniqueness rejects the overlapping save. The Settings callout tells the operator to remove OmniRoute's `orcarouter/` prefix before enabling OrcaRouter.

## API keys

Create keys at https://www.orcarouter.ai/console. Keys start with `sk-orca-`. Missing key: no outbound HTTP; status `missing_api_key`.
