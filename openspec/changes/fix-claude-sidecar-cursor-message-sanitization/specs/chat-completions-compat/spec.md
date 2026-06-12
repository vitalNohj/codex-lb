## MODIFIED Requirements

### Requirement: Route Claude model chat completions to a configured sidecar

When Claude sidecar routing is enabled, the service MUST route `POST /v1/chat/completions` requests whose effective model starts with a configured Claude sidecar prefix to the configured CLIProxyAPI sidecar instead of mapping the request into the internal Responses API flow. Prefix matching MUST be case-insensitive and MUST run after API-key enforced-model resolution and model-access validation. Configured custom alias prefixes ending in `-` or `_` MUST match either separator form for the same prefix stem.

The service MUST forward the OpenAI-compatible chat-completions JSON payload to the sidecar with the effective model name, except that configured custom alias prefixes ending in `-` or `_` MUST be stripped from the model in the forwarded sidecar payload. Before forwarding, the service MUST rewrite invalid tool-use and tool-call IDs to match `[A-Za-z0-9_-]+`, map known Cursor-native tool names to Claude Code-compatible names in the forwarded payload, and preserve unknown tool definitions unchanged in the forwarded `tools` array so CLIProxyAPI can route them to the configured provider. The service MUST accept Cursor-native `tool_result` content parts embedded in `user` messages. The service MUST sanitize forwarded `messages` by dropping empty-content messages, dropping orphan `tool` messages whose `tool_call_id` is not referenced by a prior assistant `tool_calls` entry, dropping orphan Cursor-native `tool_result` content parts whose `tool_use_id` is not referenced by a prior assistant tool-use entry, and appending a minimal `user` continuation message when the remaining conversation would otherwise end with an `assistant` message. Sidecar responses MUST restore client-requested tool names when a forward mapping was applied, including both nested `function.name` and flat `tool_calls[].name` fields. For sidecar requests, API-key validation, request-limit reservations, and request logs MUST continue to use the effective model requested by the client. The service MUST relay the sidecar's OpenAI-compatible response to the downstream client. For sidecar requests, the service MUST NOT consult Codex account selection, sticky sessions, websocket continuity, ChatGPT upstream model registry behavior, or ChatGPT upstream transport selection.

#### Scenario: Sidecar payload rejects assistant prefill for Cursor OAuth

- **GIVEN** `claude_sidecar_enabled=true`
- **WHEN** a client sends `POST /v1/chat/completions` whose `messages` array ends with an `assistant` message
- **THEN** the service forwards the request to the sidecar with a trailing `user` continuation message appended
- **AND** the forwarded payload does not end with an `assistant` message

#### Scenario: Sidecar payload drops empty messages

- **GIVEN** `claude_sidecar_enabled=true`
- **WHEN** a client sends `POST /v1/chat/completions` whose `messages` include empty-string, empty-content-array, or empty text-part entries
- **THEN** the service forwards the request to the sidecar without those empty messages

#### Scenario: Sidecar payload drops orphan tool results

- **GIVEN** `claude_sidecar_enabled=true`
- **WHEN** a client sends `POST /v1/chat/completions` whose `messages` include a `tool` message whose `tool_call_id` is not referenced by a prior assistant `tool_calls` entry
- **THEN** the service forwards the request to the sidecar without that orphan `tool` message

#### Scenario: Sidecar payload accepts and drops orphan Cursor tool-result content parts

- **GIVEN** `claude_sidecar_enabled=true`
- **WHEN** a client sends `POST /v1/chat/completions` whose `messages` include a `user` message with a Cursor-native `tool_result` content part whose `tool_use_id` is not referenced by a prior assistant tool-use entry
- **THEN** the service accepts the chat request
- **AND** the service forwards the request to the sidecar without that orphan `tool_result` content part
