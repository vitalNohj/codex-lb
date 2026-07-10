## Why

Cursor BYOK `/v1/chat/completions` mid-tool turns fail with `tool message content array contains no valid text parts` when a `role=tool` message carries a content array that has no extractable text (image-only tool results, empty text parts, or non-text structured parts). The Responses-path normalizer already JSON-serializes those arrays; chat→Responses coercion rejects them instead, so GPT-5.6 (and other native) chats die after tool use even though the same payload shape is accepted on `/v1/responses`.

## What Changes

- Coerce chat `role=tool` content arrays that lack text parts into a compact JSON string `function_call_output.output`, matching `_normalize_tool_output_value`.
- Treat arrays that only contain empty-string text parts as empty output (`""`), not as invalid.
- Keep rejecting `content: null` and non-string/non-array tool message content.
- Add regression coverage for image-only / empty-text / malformed-text-part tool messages.

## Capabilities

### New Capabilities

### Modified Capabilities
- `chat-completions-compat`: chat tool-message content arrays without text parts MUST be serialized rather than rejected when mapping to Responses `function_call_output`.

## Impact

- `app/core/openai/message_coercion.py` (`_convert_tool_message`)
- `tests/unit/test_chat_request_mapping.py`
- Cursor BYOK `/v1/chat/completions` native Codex path (GPT-5.6 and others)
