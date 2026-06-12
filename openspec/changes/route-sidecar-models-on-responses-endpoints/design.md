## Context

Sidecar routing (Claude, OpenRouter, OmniRoute) is implemented as a model-ID predicate plus a dispatch helper, but it is only invoked from `v1_chat_completions` (`app/modules/proxy/api.py:2124-2180`). The Responses endpoints — `responses` (`/backend-api/codex/responses`, `app/modules/proxy/api.py:576`) and `v1_responses` (`/v1/responses`, `:659`) — go straight to `normalize_responses_request_payload(...)`/`to_responses_request()` and then `_stream_responses`/`_collect_responses`, which select a ChatGPT/Codex account and call the upstream Responses API.

The Codex CLI talks to codex-lb over the Responses API. When an operator selects an OmniRoute model, the request lands on a Responses endpoint, skips `is_omniroute_sidecar_model`, and is sent to a ChatGPT account that returns "the model is not supported when using Codex with a ChatGPT account."

OmniRoute exposes only an OpenAI-compatible `/chat/completions` endpoint (`OmniRouteSidecarClient.chat_completion` / `stream_chat_completion`). The OmniRoute sidecar dispatch (`proxy_chat_to_omniroute`) already accepts a `ChatCompletionsRequest`, forwards it, relays the response, settles reservations, and logs with `source=omniroute_sidecar`.

The Responses request shape (`ResponsesRequest` / `V1ResponsesRequest`) is Codex-native: `instructions` (system text), `input` (string or array of typed items), `tools`, `tool_choice`, `reasoning`, `text`, `stream`, etc. OmniRoute needs chat-completions shape: `messages[]`, `tools[]`, `stream`, `stream_options`.

## Goals / Non-Goals

**Goals:**

- Consult the OmniRoute sidecar predicate on both Responses endpoints before any ChatGPT/Codex account selection, and dispatch matching models to OmniRoute.
- Reuse the existing OmniRoute dispatch/relay/settlement/logging machinery rather than duplicating it.
- Return the downstream client a valid Responses-shaped result: SSE Responses events when `stream=true`, a Responses JSON result when `stream=false`.
- Keep the non-sidecar Responses path byte-for-byte unchanged.

**Non-Goals:**

- WebSocket Responses transports (sidecar dispatch stays HTTP/SSE only this change).
- Claude/OpenRouter sidecar enablement on Responses endpoints (predicate precedence is preserved in code, but this change's specs/tests target OmniRoute, which is the reported break). The translation layer is sidecar-agnostic so the others can follow.
- Changing OmniRoute's outbound surface (still `/chat/completions`).

## Decisions

### Decision 1: Translate Responses <-> chat-completions at the sidecar boundary

OmniRoute speaks chat-completions; Codex clients speak Responses. We translate at dispatch time:

- **Request (Responses -> chat-completions):** build `messages[]` from `instructions` (as a `system`/`developer` message) plus the `input` items, map `tools`/`tool_choice` through, carry `stream`, set `stream_options.include_usage=true`. Produce a `ChatCompletionsRequest` and feed it to the existing `proxy_chat_to_omniroute`.
- **Response (chat-completions -> Responses):** wrap OmniRoute's chat-completions output back into Responses shape — for non-streaming, a single `response` result object with the assistant message as output text/tool calls; for streaming, synthesize the minimal Responses event sequence (`response.created`, output item/text deltas, `response.completed`) from the chat-completion SSE deltas.

**Why over alternatives:**

- *Forward the raw Responses payload to OmniRoute as-is*: rejected — OmniRoute has no `/responses` endpoint; it would 404 or 400.
- *Reuse `ChatCompletionsRequest.to_responses_request()` in reverse*: there is no reverse helper today; we add a focused `responses` -> chat translation used only on the sidecar branch. This keeps the existing chat path untouched.
- *Tell users to point Codex at `/v1/chat/completions`*: rejected — Codex CLI uses the Responses API; we cannot change the client contract, and `/v1/models` already advertises these models as usable.

### Decision 2: Branch placement — before account selection, after validation

Insert the sidecar check in `responses` and `v1_responses` immediately after the request payload is parsed/validated and the effective model is resolved, and before `_stream_responses`/`_collect_responses`. This mirrors the chat-completions ordering (model-access validation and API-key enforced-model resolution run first, then sidecar dispatch) so behavior is consistent across endpoints.

### Decision 3: Reservation, logging, and error contract reuse

Use the existing `proxy_chat_to_omniroute` for reservation settlement, `source=omniroute_sidecar` logging, and OpenAI error envelopes. The Responses endpoints additionally wrap the dispatch output so the streaming/non-streaming surface matches the Responses contract (e.g., error envelopes surfaced as Responses error events on the SSE stream).

## Risks / Trade-offs

- **Lossy translation of Codex-native fields (reasoning, store, previous_response_id, conversation)** → OmniRoute is a stateless chat-completions relay; we drop server-side continuity fields and forward only what chat-completions supports. Document this; sidecar models do not participate in Codex continuity. Mitigation: validate that `previous_response_id`/`conversation` are not silently treated as Codex sessions — sidecar requests never touch Codex account state.
- **Responses SSE contract drift** → downstream clients (OpenAI SDK, Codex CLI) expect a specific Responses event ordering. Mitigation: synthesize the minimal documented event sequence and cover it with integration tests on both endpoints, asserting `response.created` first and a terminal `response.completed`.
- **Precedence regressions on the chat path** → none expected; the chat-completions handler is not modified. The shared predicate functions are reused unchanged.

## Migration Plan

Pure additive routing change; no schema or migration. Deploy is safe to roll forward and back: with OmniRoute sidecar disabled or no matching selected model, the Responses path is unchanged. Rollback is removing the sidecar branch from the two Responses handlers.

## Scope finding (resolved)

All three sidecars (Claude `is_sidecar_model`, OpenRouter `is_openrouter_sidecar_model`, OmniRoute `is_omniroute_sidecar_model`) are wired **only** into `v1_chat_completions`; none are on the Responses endpoints. Claude/OpenRouter appear to "work" because they are exercised through chat-completions clients (e.g., Cursor / OpenAI SDK chat), whereas OmniRoute is exercised through the Codex CLI, which uses the Responses API and therefore hits the unrouted path.

Per maintainer direction, this change scopes the Responses-endpoint sidecar routing to **OmniRoute only** (the reported break). The translation and branch are kept sidecar-agnostic so Claude/OpenRouter can be enabled on the Responses path in a follow-up if those clients ever target it.
