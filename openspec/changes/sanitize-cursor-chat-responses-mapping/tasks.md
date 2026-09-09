## 1. Mapping

- [x] 1.1 Skip blank assistant content when decomposing chat `tool_calls`.
- [x] 1.2 Normalize structured auto/none/required/any tool choice to Responses strings.
- [x] 1.3 Canonicalize Cursor-flat function tools (`input_schema` → `parameters`, default `type=function`).
- [x] 1.4 Strip chat-only extras from forwarded Responses payloads.

## 2. Tests

- [x] 2.1 Blank `content: ""` + paired tool history maps without an empty assistant message and is account-neutral.
- [x] 2.2 `tool_choice: {"type":"auto"}` maps to `"auto"` and is account-neutral.
- [x] 2.3 Flat `input_schema` tools map to function declarations and are account-neutral.
- [x] 2.4 Chat extras are stripped; unpaired tool_calls and `container_id` stay non-neutral.
- [x] 2.5 Existing `content: null` tool-call mapping stays unchanged.

## 3. Validation

- [x] 3.1 `uv run pytest` on the mapping tests.
- [x] 3.2 `openspec validate sanitize-cursor-chat-responses-mapping --strict`.
