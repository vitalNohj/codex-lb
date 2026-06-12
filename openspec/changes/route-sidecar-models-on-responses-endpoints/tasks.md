## 1. OpenSpec artifacts

- [x] 1.1 Write proposal, design, and delta specs for OmniRoute sidecar routing on the Responses endpoints.
- [x] 1.2 Validate OpenSpec artifacts with `openspec validate route-sidecar-models-on-responses-endpoints --strict`.

## 2. Responses <-> chat-completions translation

- [x] 2.1 Add a helper that builds a `ChatCompletionsRequest` from a Responses request (`instructions` + `input` -> `messages`, map `tools`/`tool_choice`, carry `stream`).
- [x] 2.2 Add a helper that wraps an OmniRoute chat-completions JSON body into a Responses result object (non-streaming).
- [x] 2.3 Add a helper that translates OmniRoute chat-completion SSE deltas into a Responses event stream (`response.created` ... `response.completed`).
- [x] 2.4 Unit tests for request translation, non-streaming response wrapping, and streaming event synthesis.

## 3. Responses-path OmniRoute dispatch

- [x] 3.1 Add an OmniRoute sidecar dispatch entry for Responses requests that reuses reservation settlement, logging (`source=omniroute_sidecar`), and error mapping, returning a Responses-shaped response.
- [x] 3.2 Keep the translation/branch sidecar-agnostic so Claude/OpenRouter can be enabled on the Responses path later.

## 4. Wire branch into Responses endpoints

- [x] 4.1 In `responses` (`/backend-api/codex/responses`), after payload validation and effective-model resolution, dispatch OmniRoute-selected models to the sidecar before `_stream_responses`.
- [x] 4.2 In `v1_responses` (`/v1/responses`), do the same before `_stream_responses`/`_collect_responses`.
- [x] 4.3 Ensure model-access validation and API-key enforced-model resolution run before the sidecar branch, matching the chat-completions ordering.

## 5. Integration tests

- [x] 5.1 Selected OmniRoute model routes to sidecar on `/v1/responses` (streaming and non-streaming) with no ChatGPT account selected.
- [x] 5.2 Selected OmniRoute model routes to sidecar on `/backend-api/codex/responses`.
- [x] 5.3 Non-selected model keeps the existing Codex Responses path (OmniRoute receives no request).
- [x] 5.4 OmniRoute sidecar disabled does not dispatch on the Responses path.
- [x] 5.5 Reservation settles from OmniRoute usage and a request log with `source=omniroute_sidecar` is written.
- [x] 5.6 OmniRoute unreachable returns 503 (non-streaming) / terminal error event (streaming) and releases the reservation.

## 6. Final verification

- [x] 6.1 Run `uv run pytest` for the affected proxy/responses tests.
- [x] 6.2 Run `uv run ruff check` on changed files.
- [x] 6.3 Run `openspec validate route-sidecar-models-on-responses-endpoints --strict`.
