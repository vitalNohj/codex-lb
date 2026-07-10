# Tasks

- [x] Coerce non-string `tool_calls[].function.arguments` in `message_coercion._decompose_assistant_tool_calls`
- [x] Preserve `ClientPayloadError` message text in `openai_client_payload_error`
- [x] Update unit tests: object/missing arguments accepted; envelope keeps specific message
- [x] Run `openspec validate coerce-chat-tool-call-arguments --strict` and targeted pytest
