## Why

Sidecar model routing (Claude, OpenRouter, OmniRoute) is wired only into `POST /v1/chat/completions`. The Codex CLI and OpenAI-SDK Responses clients send requests to the Responses endpoints (`POST /backend-api/codex/responses` and `POST /v1/responses`), which have no sidecar branch. As a result, a request for an OmniRoute-selected model that arrives on a Responses endpoint skips the sidecar check entirely and is forwarded to the ChatGPT/Codex account upstream, which rejects it with "the model is not supported when using Codex with a ChatGPT account."

This makes OmniRoute (and the other sidecars) effectively unusable from the Codex CLI even though the model is configured, discoverable in OmniRoute, and listed in `GET /v1/models`. The defect is endpoint coverage: the routing predicate is correct, but it is never consulted on the Responses path.

## What Changes

- Route Responses-API requests whose effective model exactly matches a configured OmniRoute sidecar selected model ID to the OmniRoute sidecar, on both `POST /backend-api/codex/responses` and `POST /v1/responses`, when OmniRoute sidecar routing is enabled.
- Apply the same sidecar precedence and matching already used on `/v1/chat/completions` (Claude prefix, then OpenRouter prefix, then OmniRoute exact match) on the Responses endpoints, so a sidecar-owned model never falls through to the ChatGPT/Codex account path.
- Translate the Responses-shaped request into the OmniRoute `/chat/completions` request shape before dispatch, and translate the OmniRoute chat-completions response (streaming SSE and non-streaming JSON) back into the Responses event/result shape the downstream client expects.
- Preserve API-key authentication, model-access validation, request-limit reservation settlement/release, and `source=omniroute_sidecar` request logging for Responses-path sidecar requests, mirroring the chat-completions path.
- For OmniRoute sidecar requests on the Responses path, do not consult Codex account selection, sticky sessions, websocket continuity, ChatGPT upstream model registry, or ChatGPT upstream transport selection.

## Non-goals

- Do not change behavior for models that are not sidecar-selected; those keep the existing Responses-to-Codex path unchanged.
- Do not add sidecar routing to the Responses WebSocket transports (`ws /responses`, `ws /v1/responses`) in this change. Sidecar dispatch is HTTP/SSE only; WebSocket sidecar support is deferred.
- Do not change the Claude or OpenRouter sidecar request translation internals beyond reusing them on the Responses path.
- Do not change OmniRoute's outbound API surface; OmniRoute is still called at `/chat/completions` only.
- Do not change `GET /backend-api/codex/models`, `GET /v1/models`, or dashboard model listing behavior.
- Do not add OmniRoute OAuth, quota polling, cooling, or background workers.

## Capabilities

### Modified Capabilities

- `responses-api-compat`: exact-model sidecar dispatch for OmniRoute on the Responses endpoints, with Responses<->chat-completions translation and relay/error/stream behavior.

## Impact

- Backend proxy API flow in `app/modules/proxy/api.py` (`responses`, `v1_responses` handlers).
- New Responses<->chat-completions translation helper used by the OmniRoute sidecar dispatch on the Responses path.
- OmniRoute sidecar dispatch in `app/modules/proxy/omniroute_sidecar_dispatch.py`.
- Integration tests for Responses-path selected-model routing, streaming, non-streaming, error mapping, and reservation settlement on both `/backend-api/codex/responses` and `/v1/responses`.
