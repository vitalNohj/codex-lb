## 1. Mapping

- [ ] 1.1 Skip blank assistant content when decomposing chat `tool_calls`.
- [ ] 1.2 Normalize structured auto/none/required/any tool choice to Responses strings.
- [ ] 1.3 Canonicalize Cursor-flat function tools (`input_schema` → `parameters`, default `type=function`).
- [ ] 1.4 Strip chat-only extras from forwarded Responses payloads.

## 2. Tests

- [ ] 2.1 Blank `content: ""` + paired tool history maps without an empty assistant message and is account-neutral.
- [ ] 2.2 `tool_choice: {"type":"auto"}` maps to `"auto"` and is account-neutral.
- [ ] 2.3 Flat `input_schema` tools map to function declarations and are account-neutral.
- [ ] 2.4 Chat extras are stripped; unpaired tool_calls and `container_id` stay non-neutral.
- [ ] 2.5 Existing `content: null` tool-call mapping stays unchanged.

## 3. Validation

- [ ] 3.1 `uv run pytest` on the mapping tests.
- [ ] 3.2 `openspec validate sanitize-cursor-chat-responses-mapping --strict`.
