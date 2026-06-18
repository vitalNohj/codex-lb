## ADDED Requirements

### Requirement: DeepSeek V4 sidecar chat completions repair missing reasoning_content for tool-call history

The service MUST repair missing assistant `reasoning_content` on DeepSeek V4
tool-call continuation turns routed through any sidecar chat-completions
dispatch path (CLIProxyAPI, OpenRouter, or OmniRoute), so the upstream provider
does not reject the request with a "reasoning_content in the thinking mode must
be passed back" error. This applies only when the `/v1/chat/completions`
request's effective model is a DeepSeek V4 thinking-mode model.

The service MUST treat a model as a DeepSeek V4 model when the effective model
(case-insensitive) matches a DeepSeek V4 family token (`deepseek-v4-pro` or
`deepseek-v4-flash`, including `-`/`_` interchangeable spellings) as a model
identifier or path segment (so provider-prefixed and `-free`-suffixed forms such
as `oc/deepseek-v4-flash-free` match), OR exactly equals an operator-configured
DeepSeek alias. All other models — including non-DeepSeek OpenRouter/OmniRoute
models, Claude/CLIProxyAPI, and native Codex traffic — MUST NOT be intercepted
by this adapter.

The service MUST capture the assistant `reasoning_content` returned by the
upstream DeepSeek V4 response when the assistant turn participates in tool-call
context (the assistant message carries `tool_calls`), for both non-streaming and
streaming responses. The service MUST then, on a later outgoing DeepSeek V4
request for the same logical conversation, patch the missing `reasoning_content`
back into the assistant tool-call message in the sidecar payload before
forwarding upstream. The repair MUST mutate only the forwarded sidecar payload
and MUST NOT alter the client-visible request or response bytes.

Cached reasoning MUST be isolated such that unrelated conversations, different
configured providers (`claude` / `openrouter` / `omniroute`), different API
keys, and different DeepSeek V4 model families (`pro` vs `flash`) cannot reuse
one another's reasoning content. Cache storage MUST be bounded in size and
retention.

On the CLIProxyAPI (`claude`) path, where forwarded streamed tool-call names are
rewritten before reaching the client, reasoning capture MUST observe the raw
upstream stream (before tool-name rewriting) so the cache key matches the
re-injection key derived from the forward-sanitized outgoing payload.

When no cached reasoning is available for an assistant tool-call turn, the
service MUST forward the request unchanged (no fabricated reasoning).

The repair MUST preserve existing OpenAI-compatible streaming and non-streaming
output shapes, error envelopes and streaming error chunks, API-key access
checks, usage-reservation settlement/release, request logging, and Cursor
usage-fallback semantics. Reasoning MUST be committed to the cache only when a
streaming response completes a tool-call turn cleanly; interrupted or errored
streams MUST NOT cache partial reasoning. A cache read/write failure MUST NOT
fail the proxied request.

#### Scenario: Non-streaming tool-call reasoning is captured and re-injected

- **WHEN** a Cursor client sends a non-streaming DeepSeek V4 chat-completions
  request whose conversation produces an assistant message with `tool_calls`,
  and the upstream response includes `choices[0].message.reasoning_content`
- **THEN** the service stores that `reasoning_content` keyed to the conversation
  prefix, provider, model family, and API key
- **AND WHEN** the same client sends the next request continuing that
  conversation (the assistant tool-call message lacks `reasoning_content`, plus
  a `tool` result message)
- **THEN** the forwarded sidecar payload's assistant tool-call message includes
  the cached `reasoning_content`, while the client-facing request is unchanged

#### Scenario: Streaming tool-call reasoning is accumulated from deltas and re-injected

- **WHEN** a Cursor client sends a streaming DeepSeek V4 chat-completions
  request and the upstream stream emits `choices[0].delta.reasoning_content`
  string deltas followed by `tool_calls` deltas and a `finish_reason` of
  `tool_calls`, then `data: [DONE]`
- **THEN** the service forwards every stream chunk to the client unchanged
- **AND** stores the concatenation of the `reasoning_content` deltas keyed to
  the conversation prefix, provider, model family, and API key
- **AND WHEN** the client sends the next tool-result turn
- **THEN** the forwarded sidecar payload's assistant tool-call message includes
  the accumulated `reasoning_content`

#### Scenario: Cached reasoning is isolated across api key, provider, and model family

- **WHEN** reasoning was cached for conversation C under provider `omniroute`,
  model family `deepseek-v4-flash`, and API key K1
- **THEN** a re-injection lookup for the same conversation C under a different
  API key (K2), a different provider (`openrouter`), or a different model family
  (`deepseek-v4-pro`) MUST NOT return K1's cached reasoning
- **AND** the request for the differing context is forwarded unchanged

#### Scenario: Missing-cache request is forwarded unchanged

- **WHEN** a DeepSeek V4 request continues a conversation whose assistant
  tool-call reasoning codex-lb never observed (e.g. an imported conversation)
- **THEN** the service forwards the request unchanged without fabricating
  `reasoning_content`

#### Scenario: Interrupted streaming response does not cache partial reasoning

- **WHEN** a streaming DeepSeek V4 response emits partial
  `reasoning_content` deltas but the stream errors or ends without a clean
  tool-call completion
- **THEN** no reasoning is committed to the cache for that turn

#### Scenario: Cursor usage fallback semantics preserved for DeepSeek V4

- **WHEN** a Cursor-compat DeepSeek V4 request is repaired by the adapter and
  the upstream response omits usage (or reports zero prompt tokens)
- **THEN** the Cursor usage-fallback still applies synthetic prompt/completion
  token estimates to the client-visible response or final stream usage chunk,
  unchanged by the reasoning repair

#### Scenario: Non-DeepSeek sidecar traffic is byte-for-byte unchanged

- **WHEN** a non-DeepSeek CLIProxyAPI, OpenRouter, or OmniRoute model is routed
  through the sidecar chat-completions path
- **THEN** the forwarded sidecar payload and the client-visible response/stream
  are identical to behavior without this adapter (no reasoning capture or
  re-injection occurs)
