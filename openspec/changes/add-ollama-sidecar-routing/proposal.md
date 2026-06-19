## Why

Operators want Ollama Cloud models to be reachable through codex-lb's OpenAI-compatible Chat Completions surface while codex-lb continues to own API-key authentication, model allowlists, request-limit accounting, model catalog exposure, Settings configuration, Accounts presentation, and request-log observability.

Ollama also has local runtime use cases, but local proxy and tunnel mode introduces deployment, reachability, authentication, TLS, streaming, and SSRF constraints that are materially different from Cloud. This change implements the Cloud sidecar first and records local proxy/tunnel mode as future OpenSpec scope.

## What Changes

- Add dashboard-managed Ollama Cloud sidecar configuration with its own enable toggle, base URL, encrypted API key, model prefixes, direct full models, timeouts, cache TTL, and health fields.
- Use the official `ollama-python` SDK through an async client wrapper instead of a custom low-level HTTP client.
- Discover Ollama models from the configured Cloud endpoint and expose only cloud model IDs in dashboard model discovery.
- Add Ollama to the unified sidecar resolver so full-model and prefix matches can route `POST /v1/chat/completions` to Ollama before the native Codex path.
- Convert Ollama chat responses into OpenAI Chat Completions responses for non-streaming and streaming clients.
- Advertise only configured Ollama full models in OpenAI-compatible `GET /v1/models`; discovered-only models are not automatically exposed.
- Surface Ollama as a read-only synthetic account and show Ollama request-log rows as normal HTTP rows with account/provider label `Ollama`.
- Add Ollama as one tab in the existing Settings "External Integrations" card.

## Non-goals

- Do not implement local Ollama proxy mode, tunnel setup, operator tunnel auth, local network reachability checks, or local daemon lifecycle management.
- Do not implement embeddings, image generation, model pull/push/create/delete, or Ollama web search/fetch.
- Do not route Ollama through CLIProxyAPI/OpenRouter/OmniRoute code paths.
- Do not add Ollama pricing entries unless an authoritative pricing source is available.
- Do not change the Settings page's existing external integration card structure beyond adding the Ollama tab.
- Do not hook Ollama into `/v1/responses` in this first pass.

## Capabilities

### Modified Capabilities

- `chat-completions-compat`: Ollama sidecar routing, request adaptation, response adaptation, streaming, and error handling.
- `model-catalog-compat`: configured Ollama full-model entries in OpenAI-compatible `/v1/models`.
- `frontend-architecture`: Ollama tab in the unified external integrations Settings card.
- `api-keys`: API-key model enforcement and allowlist checks use the effective client model for Ollama requests.
- `database-migrations`: dashboard settings schema for Ollama Cloud sidecar configuration.
- `proxy-runtime-observability`: Ollama request logs, usage, cost-null behavior, and synthetic account presentation.

## Impact

- Backend settings persistence and migration for Ollama sidecar configuration.
- New Ollama SDK wrapper in `app/core/clients/ollama_sidecar.py`.
- New Ollama dashboard module under `app/modules/ollama_sidecar/`.
- Chat Completions proxy routing in `app/modules/proxy/api.py`.
- Sidecar resolver provider order in `app/modules/proxy/sidecar_routing.py`.
- Accounts and request-log presentation for Ollama sidecar rows.
- Frontend Settings schemas, API calls, hooks, mocks, and external integrations tabs.
- Unit and integration tests for settings, routing, model catalog, client behavior, dashboard APIs, request logs, and frontend Settings behavior.
