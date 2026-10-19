## 1. Request translation

- [x] 1.1 Convert function, custom and namespace tools to chat function tools and record their Responses shape.
- [x] 1.2 Omit cached `web_search`; reject every other hosted tool with a 400.
- [x] 1.3 Reject `previous_response_id`, `conversation` and `store: true` (capture the client's `store` before it is forced false).
- [x] 1.4 Map `reasoning.effort`, `max_output_tokens`, `temperature`, `top_p` and `text.format`.
- [x] 1.5 Keep multiple text parts separate; keep a single part a string.
- [x] 1.6 Map `custom_tool_call(_output)`, namespaced calls, `input_file` with `file_data`, `agent_message` and `additional_tools`; reject unmappable items and parts.
- [x] 1.7 Translate before reserving quota and answer a translation error with an OpenAI 400.

## 2. Response translation

- [x] 2.1 Return chat tool calls as `function_call` or `custom_tool_call` with their original name and namespace.
- [x] 2.2 Map cached, cache-write and reasoning token details into Responses usage.
- [x] 2.3 Emit the full Responses stream event sequence with `sequence_number`, `response.incomplete` for length/content-filter stops and `response.failed` for upstream errors.
- [x] 2.4 Echo `tools`, `tool_choice` and `parallel_tool_calls` on Responses objects.

## 3. Chat builders

- [x] 3.1 Normalize flat function tools in the OpenAI-compatible, OpenRouter and OrcaRouter chat builders.

## 4. Verification

- [x] 4.1 Unit regression tests for each finding, replaying streams through the OpenAI SDK's Responses stream state machine.
- [x] 4.2 Integration tests on `/v1/responses` and `/backend-api/codex/responses`.
- [x] 4.3 End-to-end lab: real CLIProxyAPI v8.0.32 with a mock Anthropic upstream, before and after.
