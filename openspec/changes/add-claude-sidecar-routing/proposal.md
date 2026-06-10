## Why

Cursor can use a custom OpenAI-compatible base URL, but codex-lb currently routes `/v1/chat/completions` only through its ChatGPT/Codex upstream. Operators who already run CLIProxyAPI for Claude Pro OAuth need codex-lb to recognize Claude custom model IDs from Cursor and delegate those requests to the CLIProxyAPI sidecar instead of trying to send them to ChatGPT.

This keeps Claude OAuth, Anthropic translation, tool-call mapping, and vision handling inside CLIProxyAPI while preserving codex-lb's existing API-key guard, model allowlist checks, and rate-limit accounting surface.

## What Changes

- Add dashboard-managed CLIProxyAPI sidecar configuration with environment values used only as initial defaults.
- Add a small outbound sidecar HTTP client for `/v1/models` and `/v1/chat/completions`.
- Route `/v1/chat/completions` requests whose effective model starts with a configured Claude sidecar prefix to the sidecar when enabled.
- Relay sidecar non-streaming JSON and streaming SSE responses without translating them to codex-lb's internal Responses API shape.
- Merge sidecar models into OpenAI-compatible `GET /v1/models` and dashboard `GET /api/models` while keeping `GET /backend-api/codex/models` unchanged.
- Preserve API-key model access checks and request-limit reservation settlement/release for sidecar requests.
- Surface CLIProxyAPI as a read-only synthetic Claude account in the Accounts dashboard.
- Add dashboard status, model listing, and test-connection APIs for CLIProxyAPI.
- Show sidecar request source clearly in dashboard request logs.

## Non-goals

- Do not add an Anthropic-native `/v1/messages` endpoint to codex-lb.
- Do not port Claude OAuth or Anthropic request translation into codex-lb.
- Do not manage the CLIProxyAPI process lifecycle from codex-lb.
- Do not manage a Cursor tunnel from codex-lb.
- Do not add Claude quota scraping beyond API-key reservation accounting, request logs, and sidecar health/model checks.

## Capabilities

### Modified Capabilities

- `chat-completions-compat`: model-prefix dispatch for Claude sidecar requests and sidecar error/stream behavior.
- `model-catalog-compat`: sidecar model entries in OpenAI-compatible `/v1/models` only.
- `api-keys`: API-key model restrictions and usage reservations apply to sidecar requests.
- `dashboard-sidecar-management`: dashboard persistence, health checks, synthetic account display, API-key model controls, and request-log source display for the sidecar.

## Impact

- Backend proxy API flow in `app/modules/proxy/api.py`.
- New outbound client in `app/core/clients/claude_sidecar.py`.
- New sidecar dispatch helper in `app/modules/proxy/claude_sidecar_dispatch.py`.
- Static env defaults in `app/core/config/settings.py` and `.env.example`.
- Dashboard settings persistence and migration for sidecar configuration.
- New dashboard sidecar status/test/model APIs.
- Dashboard Accounts, Settings, API-key, and request-log UI.
- Unit/integration tests for routing, streaming, error mapping, model list merge, and reservation settlement.
