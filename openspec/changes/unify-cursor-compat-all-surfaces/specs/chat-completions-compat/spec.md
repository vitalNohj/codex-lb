## ADDED Requirements

### Requirement: Cursor GPT-5.6 success-path proactive compaction

The service MUST rewrite chat-completions usage to synthetic over-limit prompt tokens (`1_000_000`) for Cursor-compatible clients when the request model matches `gpt-5.6-*` (case-insensitive) and reported `usage.prompt_tokens` is at least `350_000`, even when the upstream response is success with no context-length error. Non-`gpt-5.6-*` models MUST keep error-path-only Cursor compaction. Below-threshold GPT-5.6 usage MUST remain unchanged.

#### Scenario: Cursor GPT-5.6 Sol at threshold inflates usage

- **GIVEN** a Cursor-compatible chat-completions response for `gpt-5.6-sol` with `prompt_tokens` of `350000`
- **WHEN** chat usage fallback runs (non-stream or stream usage chunk)
- **THEN** the returned usage uses `prompt_tokens=1000000` and `total_tokens=1000000 + completion_tokens`

#### Scenario: Cursor GPT-5.6 Sol below threshold is unchanged

- **GIVEN** a Cursor-compatible chat-completions response for `gpt-5.6-sol` with `prompt_tokens` of `349999`
- **WHEN** chat usage fallback runs
- **THEN** the returned usage keeps the original prompt token count

#### Scenario: Cursor non-GPT-5.6 high usage stays error-path only

- **GIVEN** a Cursor-compatible chat-completions response for `gpt-5.5-*` with high success-path `prompt_tokens`
- **WHEN** chat usage fallback runs without a context-length error
- **THEN** the service does not apply proactive synthetic over-limit inflation

### Requirement: Cursor-compatible chat context-limit handling covers late and sidecar non-stream failures

The service MUST return the synthetic Cursor over-limit chat completion for every context-length failure on `POST /v1/chat/completions` when the downstream client is Cursor-compatible, including failures detected after stream startup on non-streaming requests.

For non-streaming Cursor-compatible chat requests routed to a sidecar provider, the service MUST return the synthetic over-limit chat completion when the provider reports a context-length failure, for every sidecar provider. Sidecar dispatchers MUST use one shared context-length detector rather than provider-specific Cursor logic. For clients that are not Cursor-compatible, the service MUST continue to surface the provider error unchanged.

#### Scenario: Cursor late non-stream context error returns synthetic usage

- **GIVEN** a Cursor-compatible non-streaming chat-completions request
- **WHEN** the upstream reports a context-length failure after stream startup succeeded
- **THEN** the service returns HTTP 200 with synthetic over-limit usage instead of an error envelope

#### Scenario: Cursor sidecar non-stream context error returns synthetic usage

- **GIVEN** a Cursor-compatible non-streaming chat-completions request routed to an OpenRouter, OmniRoute, or Ollama sidecar
- **WHEN** the sidecar reports a context-length failure
- **THEN** the service returns HTTP 200 with synthetic over-limit usage instead of the provider error envelope

#### Scenario: Non-Cursor sidecar context error is unchanged

- **GIVEN** a non-Cursor non-streaming chat-completions request routed to a sidecar
- **WHEN** the sidecar reports a context-length failure
- **THEN** the service returns the provider error envelope and status unchanged
