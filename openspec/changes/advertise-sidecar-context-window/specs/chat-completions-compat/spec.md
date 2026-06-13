## ADDED Requirements

### Requirement: Cursor-compatible chat requests do not preflight large context as API-key rate limit

The system MUST use a default API-key request reservation for
Cursor-compatible `POST /v1/chat/completions` requests instead of a locally
estimated large prompt/context budget. The system MUST continue settling actual
API-key usage from the upstream response usage when available.

This preserves Cursor's ability to interpret model/context-window failures and
invoke its own compaction flow instead of surfacing a misleading "user provided
API key" rate-limit error.

#### Scenario: Cursor request uses the default reservation

- **GIVEN** a Cursor-compatible chat-completions request with a large Responses-shaped `input`
- **WHEN** the request enters API-key reservation enforcement
- **THEN** the local request reservation uses the default request budget rather than the full estimated prompt size

#### Scenario: Cursor late context error uses synthetic usage

- **GIVEN** a Cursor-compatible streaming chat-completions request
- **AND** the upstream emits a context-window error after the stream has started
- **WHEN** the proxy adapts the Responses stream to chat-completions chunks
- **THEN** the proxy emits a synthetic high-usage completion stream instead of forwarding the error envelope

#### Scenario: Non-Cursor request keeps local request sizing

- **GIVEN** a non-Cursor chat-completions request with a Responses-shaped `input`
- **WHEN** the request enters API-key reservation enforcement
- **THEN** the local request reservation may use the estimated prompt-size budget
