## ADDED Requirements

### Requirement: Map Cursor chat tool grammar onto portable Responses input

When mapping `/v1/chat/completions` onto Responses, the service MUST emit an account-neutral fresh-replay body for a self-contained Composer-style history: nested or Cursor-flat function tools, string or structured `auto`/`none`/`required` tool choice, and paired `tool_calls` whose assistant `content` is blank. The service MUST NOT invent portability for unpaired tool calls or account-scoped tool fields such as `container_id`.

#### Scenario: Blank assistant content next to tool_calls is omitted

- **WHEN** an assistant message has `content: ""` (or only blank text parts) and `tool_calls`
- **THEN** the mapped Responses `input` contains the `function_call` items without an empty `output_text` assistant message

#### Scenario: Structured auto tool choice maps to a string

- **WHEN** the client sends `tool_choice: {"type": "auto"}` without a function name
- **THEN** the mapped Responses `tool_choice` is `"auto"`

#### Scenario: Cursor-flat input_schema tools map to function declarations

- **WHEN** the client sends a tool `{ "name": "...", "input_schema": { ... } }`
- **THEN** the mapped Responses tools entry is a function declaration with `type=function` and `parameters` copied from `input_schema`

#### Scenario: Unpaired tool_calls stay non-portable

- **WHEN** the mapped input ends with a `function_call` that has no matching `function_call_output`
- **THEN** the body is not classified as an account-neutral fresh replay
