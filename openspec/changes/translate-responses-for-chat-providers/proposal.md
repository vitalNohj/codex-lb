## Why

Responses requests for Claude, OpenRouter, OrcaRouter, Ollama, OpenAI-compatible,
OmniRoute and OpenCode Go models are translated into Chat Completions requests.
The reliability audit (PR-B, findings T2-T9) found that translation silently
changed the request and the answer:

- Flat Responses function tools reached OpenAI-compatible, OpenRouter and
  OrcaRouter upstreams unconverted; custom (freeform) and namespace tools, and
  hosted tools, were forwarded raw or dropped.
- `previous_response_id`, `conversation` and `store: true` were dropped, so a
  follow-up ran without its history and still returned 200.
- `reasoning.effort`, `max_output_tokens`, `temperature`, `top_p` and
  `text.format` were dropped.
- Multiple text parts were joined with no separator ("part A" + "part B" ->
  "part Apart B").
- Usage lost `cached_tokens` and `reasoning_tokens`, which hid prompt-cache
  misses.
- The synthesized stream lacked `response.in_progress`,
  `response.content_part.added/done`, `response.output_text.done` and
  `sequence_number`. The official OpenAI SDK stream parser raised on the first
  text delta, and a mid-stream upstream error ended without a terminal
  Responses event.
- `custom_tool_call`, `input_file` and other input items were dropped.

## What Changes

- Every Responses field either maps onto its Chat Completions equivalent or
  the request is rejected with an OpenAI-shaped 400 that names the parameter,
  before any quota is reserved. Nothing meaningful is dropped silently.
- Tools: function (flat or nested) -> chat function; custom -> chat function
  taking `{"input": string}` whose calls return as `custom_tool_call`;
  namespace children -> `<namespace>__<child>` functions whose calls return
  with `namespace`; `web_search` with `external_web_access: false` (Codex CLI's
  default cached mode) is omitted; every other hosted tool is rejected.
- `previous_response_id`, `conversation` and `store: true` are rejected.
- `reasoning.effort` -> `reasoning_effort`, `max_output_tokens` -> `max_tokens`,
  `temperature`, `top_p`, `text.format` -> `response_format`.
- Text parts stay separate; a single text part is still sent as a string, so
  the common request is byte-identical and keeps its cache prefix.
- Usage carries `input_tokens_details.cached_tokens`/`cache_write_tokens` and
  `output_tokens_details.reasoning_tokens`, streamed and not.
- The stream emits the full Responses event sequence with `sequence_number`,
  maps finish reasons `length`/`content_filter` to `response.incomplete`, and
  ends an upstream error with `response.failed`.
- Chat provider builders for OpenAI-compatible, OpenRouter and OrcaRouter
  normalize flat function tools on `/v1/chat/completions` too.

## Non-goals

- `prompt_cache_key` forwarding (audit T1) is owned by a separate change.
- Native Responses pass-through for providers that speak Responses (audit PR-E).

## Capabilities

### Modified Capabilities

- `responses-api-compat`: Responses -> chat-provider translation fidelity.
