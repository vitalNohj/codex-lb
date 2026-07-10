# Chat Completions Compatibility Delta

## ADDED Requirements

### Requirement: Coerce non-string tool call arguments

The service MUST coerce non-string `tool_calls[].function.arguments` values on assistant chat messages into JSON strings when mapping `/v1/chat/completions` requests to the Responses wire format. Missing arguments MUST become `"{}"`. Object and array arguments MUST be serialized with compact JSON (`json.dumps` with `separators=(",", ":")`). The service MUST NOT reject the request solely because arguments arrived as a JSON object instead of a string.

#### Scenario: Object arguments accepted

- **WHEN** a client sends an assistant message with `tool_calls[].function.arguments` as a JSON object (for example `{"command":"ls"}`)
- **THEN** the mapped Responses `function_call` input item MUST carry a string `arguments` value equal to the compact JSON serialization of that object

#### Scenario: Missing arguments default to empty object

- **WHEN** a client sends an assistant `tool_calls` entry whose `function` object omits `arguments`
- **THEN** the mapped Responses `function_call` input item MUST use `arguments` equal to `"{}"`

### Requirement: Preserve ClientPayloadError detail in chat validation envelopes

When `/v1/chat/completions` rejects a payload via `ClientPayloadError`, the OpenAI error envelope MUST include the exception's message text (not only the generic phrase "Invalid request payload") and MUST preserve `param` when set.

#### Scenario: Messages param keeps specific message

- **WHEN** message coercion raises `ClientPayloadError` with `param="messages"` and a specific message string
- **THEN** the 400 OpenAI error envelope MUST set `error.param` to `messages` and `error.message` to that specific string
