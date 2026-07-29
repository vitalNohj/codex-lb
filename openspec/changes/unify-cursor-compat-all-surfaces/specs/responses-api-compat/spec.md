## ADDED Requirements

### Requirement: Cursor-compatible Responses requests receive context-limit compaction signals

The service MUST apply the same Cursor context-limit compaction semantics on `POST /v1/responses` and `POST /backend-api/codex/responses` that Cursor-compatible `POST /v1/chat/completions` requests already receive, using the same Cursor client detection.

When a downstream client is identified as Cursor-compatible and a Responses request fails because of an upstream context-length limit, the service MUST return a successful Responses turn whose usage reports the synthetic over-limit token count, and MUST NOT forward the context-length error envelope or a `response.failed` event for that failure. This MUST apply whether the failure is detected during stream startup, mid-stream, or while collecting a non-streaming response.

This behavior MUST NOT depend on the requested model. For clients that are not Cursor-compatible, the service MUST continue to surface context-length failures unchanged.

#### Scenario: Cursor streaming Responses context limit returns synthetic completion

- **GIVEN** a Cursor-compatible client sends a streaming Responses request
- **WHEN** the upstream reports a context-length failure after the stream has started
- **THEN** the downstream stream ends with a `response.completed` event whose usage reports the synthetic over-limit token count
- **AND** the downstream stream contains no `response.failed` event

#### Scenario: Cursor non-streaming Responses context limit returns synthetic completion

- **GIVEN** a Cursor-compatible client sends a non-streaming Responses request
- **WHEN** the upstream reports a context-length failure
- **THEN** the service returns HTTP 200 with a completed Responses payload whose usage reports the synthetic over-limit token count

#### Scenario: Cursor Responses context limit at stream startup returns synthetic completion

- **GIVEN** a Cursor-compatible client sends a streaming Responses request
- **WHEN** the upstream reports a context-length failure before the stream produces output
- **THEN** the service returns a successful event stream whose `response.completed` usage reports the synthetic over-limit token count

#### Scenario: Non-Cursor Responses context limit is unchanged

- **GIVEN** a client that is not Cursor-compatible sends a Responses request
- **WHEN** the upstream reports a context-length failure
- **THEN** the service surfaces the context-length failure as it did before, without synthetic usage

#### Scenario: Cursor compaction signal is model independent

- **GIVEN** Cursor-compatible Responses requests for different models
- **WHEN** each upstream reports a context-length failure
- **THEN** every response carries the same synthetic over-limit usage semantics
