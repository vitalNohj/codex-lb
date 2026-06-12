## Why

Operators want OpenRouter models available through codex-lb's API-key guard, model allowlists, and request accounting without routing those requests through the native ChatGPT/Codex upstream or the existing Claude/CLIProxyAPI sidecar.

OpenRouter exposes a direct OpenAI-compatible API. codex-lb can relay matching chat-completions requests to OpenRouter with a thinner integration than the Claude sidecar requires.

## What Changes

- Add dashboard-managed OpenRouter sidecar configuration with environment values used only as initial defaults.
- Add an outbound OpenRouter HTTP client for `/v1/models` and `/v1/chat/completions`.
- Route `/v1/chat/completions` requests whose effective model starts with a configured OpenRouter sidecar prefix to OpenRouter when enabled, after Claude sidecar prefix checks and before the native Codex path.
- Relay OpenRouter non-streaming JSON and streaming SSE responses without translating them to codex-lb's internal Responses API shape.
- Merge OpenRouter models into OpenAI-compatible `GET /v1/models` and dashboard `GET /api/models` while keeping `GET /backend-api/codex/models` unchanged.
- Preserve API-key model access checks and request-limit reservation settlement/release for OpenRouter sidecar requests.
- Surface OpenRouter as a read-only synthetic account in the Accounts dashboard.
- Add dashboard status, model listing, and test-connection APIs for OpenRouter.
- Show OpenRouter sidecar request source clearly in dashboard request logs.

## Non-goals

- Do not refactor or generalize the Claude/CLIProxyAPI sidecar.
- Do not route OpenRouter through CLIProxyAPI openai-compatibility config.
- Do not add OpenRouter OAuth or token lifecycle inside codex-lb.
- Do not add quota polling, usage queue, auth plans, or background workers for OpenRouter in this change.
- Do not add Claude-style tool/message sanitization for OpenRouter requests.
- Do not manage the OpenRouter process lifecycle from codex-lb.

## Capabilities

### Modified Capabilities

- `chat-completions-compat`: model-prefix dispatch for OpenRouter sidecar requests and relay/error/stream behavior.
- `model-catalog-compat`: OpenRouter model entries in OpenAI-compatible `/v1/models` only.
- `api-keys`: API-key model restrictions and usage reservations apply to OpenRouter sidecar requests.

### New Capabilities

- `openrouter-sidecar-management`: dashboard persistence, health checks, synthetic account display, API-key model controls, and request-log source display for OpenRouter.

## Impact

- Backend proxy API flow in `app/modules/proxy/api.py`.
- New outbound client in `app/core/clients/openrouter_sidecar.py`.
- New sidecar dispatch helper in `app/modules/proxy/openrouter_sidecar_dispatch.py`.
- Static env defaults in `app/core/config/settings.py` and `.env.example`.
- Dashboard settings persistence and migration for OpenRouter sidecar configuration.
- New dashboard OpenRouter sidecar status/test/model APIs.
- Dashboard Accounts, Settings, API-key, and request-log UI.
- Unit/integration tests for routing, streaming, error mapping, model list merge, and reservation settlement.
