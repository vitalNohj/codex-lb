## ADDED Requirements

### Requirement: Claude sidecar payloads repair unanswered tool calls

The Claude sidecar chat-completions forward path MUST insert a placeholder `tool` message for every assistant `tool_calls[].id` that is not answered by a `tool` message before the next non-`tool` message, so the forwarded conversation never contains a `tool_use` without a following `tool_result`. Placeholder messages MUST be inserted immediately after the assistant turn that issued the call, MUST carry the unanswered `tool_call_id`, and MUST use a fixed non-empty content string indicating the call was not completed. Existing `tool` messages MUST be preserved in their original order and MUST NOT be duplicated. Assistant turns whose calls are all answered MUST be forwarded unchanged.

#### Scenario: Aborted tool call gets a placeholder result

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar
- **AND** the messages contain an assistant turn with `tool_calls` id `call_1` followed directly by a `user` message
- **WHEN** the service builds the sidecar payload
- **THEN** a `tool` message with `tool_call_id` `call_1` is inserted between the assistant turn and the user message
- **AND** the forwarded payload otherwise preserves the original messages

#### Scenario: Partially answered parallel tool calls are completed

- **GIVEN** an assistant turn with `tool_calls` ids `call_1` and `call_2` followed by a `tool` message for `call_1` only
- **WHEN** the service builds the sidecar payload
- **THEN** the existing `tool` message for `call_1` is kept
- **AND** a placeholder `tool` message for `call_2` is added before the next non-`tool` message

#### Scenario: Fully answered tool calls are unchanged

- **GIVEN** an assistant turn with `tool_calls` id `call_1` followed by a `tool` message for `call_1`
- **WHEN** the service builds the sidecar payload
- **THEN** no placeholder message is inserted

### Requirement: Claude sidecar payloads drop duplicate tool definitions

The Claude sidecar chat-completions forward path MUST drop any tool definition whose function name matches an earlier tool definition in the same `tools` array, keeping the first occurrence, so the forwarded `tools` array never repeats a name. Name comparison is applied after the Cursor-to-Claude-Code tool name mapping, so two client names that map to the same wire name are still forwarded as distinct uniquely-suffixed tools as before.

#### Scenario: Duplicate tool definitions are collapsed

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with two tool definitions named `lookup`
- **WHEN** the service builds the sidecar payload
- **THEN** the forwarded `tools` array contains exactly one definition named `lookup`
- **AND** it is the first definition the client sent
