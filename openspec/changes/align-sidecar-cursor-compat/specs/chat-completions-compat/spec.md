## MODIFIED Requirements

### Requirement: Cursor-compatible Chat Completions sidecar streams use shared Cursor usage semantics

When a downstream client is identified as Cursor-compatible and a `/v1/chat/completions` request is routed to a sidecar provider, the service MUST apply the same Cursor usage fallback and context-limit synthetic usage behavior that native Cursor chat completions use after the sidecar has produced OpenAI chat-completions shaped output. Provider-specific sidecar stream transformations MAY run before the shared Cursor layer, but sidecar dispatchers MUST NOT implement separate provider-specific Cursor usage fallback behavior.

For Cursor-compatible sidecar streams, the service MUST request provider usage metadata by forwarding `stream_options.include_usage=true`. If the sidecar stream includes a final OpenAI chat usage chunk with usable `prompt_tokens` and `completion_tokens`, the service MUST forward that usage unchanged. If the sidecar stream completes without usable usage metadata, the service MUST emit one estimated usage chunk before `data: [DONE]`. If the sidecar stream emits an OpenAI error envelope representing a context-length failure, the service MUST replace that error with the existing synthetic high-usage Cursor compaction stream and MUST NOT forward the original error envelope.

For non-Cursor sidecar streams, the service MUST NOT add Cursor-only estimated usage when the provider omits usage metadata. Sidecar request-limit reservation settlement MAY still use provider usage metadata observed before any downstream Cursor-only rewriting.

#### Scenario: Cursor sidecar stream forwards valid final usage unchanged

- **GIVEN** a Cursor-compatible client sends a streaming sidecar chat-completions request
- **WHEN** the sidecar emits OpenAI chat-completion chunks and a final usage chunk with positive `prompt_tokens` and integer `completion_tokens`
- **THEN** the downstream stream contains that final usage chunk unchanged
- **AND** the stream terminates with `data: [DONE]`

#### Scenario: Cursor sidecar stream receives estimated usage when provider omits usage

- **GIVEN** a Cursor-compatible client sends a streaming sidecar chat-completions request
- **WHEN** the sidecar emits OpenAI chat-completion chunks and `data: [DONE]` without a usable final usage chunk
- **THEN** the downstream stream includes exactly one estimated usage chunk before `data: [DONE]`
- **AND** the estimated usage has non-zero `prompt_tokens`, non-zero `completion_tokens`, and `total_tokens` equal to their sum

#### Scenario: Cursor sidecar stream receives synthetic usage for context-limit errors

- **GIVEN** a Cursor-compatible client sends a streaming sidecar chat-completions request
- **WHEN** the sidecar emits an OpenAI error envelope whose code or message identifies a context-length failure
- **THEN** the downstream stream returns synthetic usage with `prompt_tokens=1000000`, `completion_tokens=0`, and `total_tokens=1000000`
- **AND** the downstream stream does not include the original error envelope
- **AND** the stream terminates with `data: [DONE]`

#### Scenario: Non-Cursor sidecar stream keeps missing usage missing

- **GIVEN** a non-Cursor client sends a streaming sidecar chat-completions request
- **WHEN** the sidecar emits OpenAI chat-completion chunks and `data: [DONE]` without a usable final usage chunk
- **THEN** the downstream stream does not include a Cursor-only estimated usage chunk
- **AND** the stream terminates with `data: [DONE]`
