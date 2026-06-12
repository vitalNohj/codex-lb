## Why

Operators want a first-class OmniRoute sidecar inside codex-lb so OmniRoute-managed models can be reached through codex-lb's OpenAI-compatible surface while codex-lb keeps owning API-key authentication, model allowlists, request-limit accounting, and dashboard observability. OmniRoute already exposes its own dashboard at `/omni` and handles its own provider cooling, but operators still need codex-lb to dispatch only the model IDs they explicitly choose to OmniRoute and to leave every other model on the existing native Codex path.

OmniRoute exposes a direct OpenAI-compatible API similar to OpenRouter, so the integration is a relay client rather than a Claude-style sidecar with message sanitization or auth plans.

## What Changes

- Add dashboard-managed OmniRoute sidecar configuration with environment values used only as initial defaults.
- Add an outbound OmniRoute HTTP client for `/models` and `/chat/completions` under a configurable base URL.
- Route `POST /v1/chat/completions` requests whose effective model exactly matches a configured OmniRoute selected model ID to OmniRoute when enabled, after Claude and OpenRouter sidecar checks and before the native Codex path.
- Relay OmniRoute non-streaming JSON and streaming SSE responses without translating them to codex-lb's internal Responses API shape.
- Merge OmniRoute models into OpenAI-compatible `GET /v1/models` and dashboard `GET /api/models` while keeping `GET /backend-api/codex/models` unchanged.
- Preserve API-key model access checks and request-limit reservation settlement/release for OmniRoute sidecar requests.
- Surface OmniRoute as a read-only synthetic account in the Accounts dashboard.
- Add dashboard status, model listing, and test-connection APIs for OmniRoute.
- Show OmniRoute sidecar request source clearly in dashboard request logs.
- Add a Settings card labeled `OmniRoute Sidecar` with API key, exact selected-model controls, model discovery, health, and a link to `/omni`.

## Non-goals

- Do not refactor or generalize the Claude or OpenRouter sidecars.
- Do not route OmniRoute through CLIProxyAPI openai-compatibility config.
- Do not add OmniRoute OAuth or token lifecycle inside codex-lb.
- Do not add quota polling, cooling, usage queue, auth plans, or background workers for OmniRoute in this change. OmniRoute owns its own cooling.
- Do not add Claude-style tool/message sanitization for OmniRoute requests.
- Do not manage the OmniRoute process lifecycle from codex-lb.
- Do not change the existing `/omni` reverse proxy behavior.

## Capabilities

### Modified Capabilities

- `chat-completions-compat`: exact-model dispatch for OmniRoute sidecar requests and relay/error/stream behavior.
- `model-catalog-compat`: OmniRoute model entries in OpenAI-compatible `/v1/models` only.
- `api-keys`: API-key model restrictions and usage reservations apply to OmniRoute sidecar requests.

### New Capabilities

- `omniroute-sidecar-management`: dashboard persistence, health checks, synthetic account display, settings UI, and request-log source display for OmniRoute.

## Impact

- Backend proxy API flow in `app/modules/proxy/api.py`.
- New outbound client in `app/core/clients/omniroute_sidecar.py`.
- New sidecar dispatch helper in `app/modules/proxy/omniroute_sidecar_dispatch.py`.
- Static env defaults in `app/core/config/settings.py`.
- Dashboard settings persistence and migration for OmniRoute sidecar configuration.
- New dashboard OmniRoute sidecar status/test/model APIs.
- Dashboard Accounts, Settings, and request-log UI for OmniRoute.
- Unit and integration tests for routing, streaming, error mapping, model list merge, and reservation settlement.
