## ADDED Requirements

### Requirement: Chat-provider Responses translation rejects instead of dropping

When a Responses request is served by a chat-completions provider (Claude, OpenRouter, OrcaRouter, Ollama, OpenAI-compatible, OmniRoute or OpenCode Go), the service MUST map every field that changes the turn onto its Chat Completions equivalent, or respond 400 with an OpenAI error envelope whose `param` names the field. Translation MUST happen before API-key quota is reserved, and a rejected request MUST NOT reach the provider.

#### Scenario: Server-side state fields are rejected

- **WHEN** a client sends `previous_response_id`, `conversation`, or `store: true`
- **THEN** the service responds 400 with `code: "unsupported_parameter"` and `param` naming the field
- **AND** no quota reservation is created and the provider receives nothing

#### Scenario: Unmappable input is rejected

- **WHEN** input contains `item_reference`, `local_shell_call`, `compaction`, an `input_file` with only a `file_id` or `file_url`, an `input_image` with only a `file_id`, or `input_audio`
- **THEN** the service responds 400 with `param` naming the item or content part

#### Scenario: Opaque hints are omitted

- **WHEN** a request carries encrypted `reasoning` items, `web_search_call` items, `text.verbosity` or `reasoning.summary`
- **THEN** they are not sent to the provider and the request proceeds

### Requirement: Chat-provider Responses tools keep their shape

Responses tools MUST be sent as chat function tools, and the provider's tool calls MUST be returned in the declared tool's Responses shape.

#### Scenario: Flat function tools are sent in chat shape

- **WHEN** a client sends `tools: [{"type": "function", "name": "lookup", "parameters": {...}}]`
- **THEN** the provider receives `{"type": "function", "function": {"name": "lookup", "parameters": {...}}}`
- **AND** a `tool_choice` naming the function is sent as `{"type": "function", "function": {"name": "lookup"}}`

#### Scenario: Custom tools round-trip as custom tool calls

- **WHEN** a client declares `{"type": "custom", "name": "apply_patch"}`
- **THEN** the provider receives a function `apply_patch` taking one required string property `input`
- **AND** a provider call with arguments `{"input": "<text>"}` is returned as a `custom_tool_call` with `input: "<text>"`
- **AND** a `custom_tool_call` input item is replayed as a tool call with arguments `{"input": "<text>"}`

#### Scenario: Namespace tools are flattened and mapped back

- **WHEN** a client declares namespace `mcp__docs` with child function `search`
- **THEN** the provider receives a function `mcp__docs__search`
- **AND** its calls return as `function_call` with `name: "search"` and `namespace: "mcp__docs"`

#### Scenario: Cached web search is omitted and hosted tools are rejected

- **WHEN** a client declares `{"type": "web_search", "external_web_access": false}`
- **THEN** that tool is not sent and the request proceeds
- **WHEN** a client declares a live `web_search`, `file_search`, `code_interpreter`, `image_generation`, `local_shell`, `computer_use_preview` or `mcp` tool
- **THEN** the service responds 400 with `param: "tools[<index>]"`

### Requirement: Chat-provider Responses requests forward sampling and content faithfully

The service MUST forward `reasoning.effort`, `max_output_tokens`, `temperature`, `top_p` and `text.format`, and MUST keep separate text parts separate.

#### Scenario: Sampling, reasoning and output format are forwarded

- **WHEN** a client sends `reasoning.effort`, `max_output_tokens`, `temperature`, `top_p` and a `json_schema` `text.format`
- **THEN** the provider receives `reasoning_effort`, `max_tokens`, `temperature`, `top_p` and `response_format` with the schema under `json_schema`

#### Scenario: Text parts are not joined

- **WHEN** a message has two `input_text` parts "part A" and "part B"
- **THEN** the provider receives two text parts, not "part Apart B"
- **AND** a message with one text part is still sent as string content

#### Scenario: Inline files are forwarded

- **WHEN** an `input_file` carries `file_data`
- **THEN** the provider receives a chat `file` part with that `file_data` and `filename`

### Requirement: Chat-provider Responses usage keeps token details

Responses usage built from chat usage MUST include `input_tokens_details.cached_tokens`, `input_tokens_details.cache_write_tokens` and `output_tokens_details.reasoning_tokens` (zero when the provider omits them), streamed and not.

#### Scenario: Cache hits are visible to the client

- **WHEN** the provider reports `prompt_tokens_details.cached_tokens: 705` and `completion_tokens_details.reasoning_tokens: 12`
- **THEN** Responses usage reports `input_tokens_details.cached_tokens: 705` and `output_tokens_details.reasoning_tokens: 12`

### Requirement: Chat-provider Responses streams emit the full event sequence

A streamed chat-provider response MUST emit events the OpenAI SDK accepts, each with a `sequence_number` counting from 0, including `response.in_progress`, `response.content_part.added/done` and `response.output_text.done`, and exactly one terminal event.

#### Scenario: The OpenAI SDK stream parser accepts the stream

- **WHEN** a client streams a chat-provider model with the OpenAI Python SDK's `responses.stream()`
- **THEN** the SDK accumulates the text and returns the final response with usage

#### Scenario: Stop reasons map to Responses terminals

- **WHEN** the provider stops with `finish_reason: "length"`
- **THEN** the stream ends with `response.incomplete` and `incomplete_details.reason: "max_output_tokens"`

#### Scenario: A mid-stream provider error ends with response.failed

- **WHEN** the provider sends an error chunk after some text
- **THEN** the stream ends with `response.failed` whose `error.code` is a Responses error code
