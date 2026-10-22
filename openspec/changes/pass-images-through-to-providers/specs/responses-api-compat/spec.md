## ADDED Requirements

### Requirement: Responses images reach chat providers unchanged

When a Responses request is served by a chat-completions provider, every `input_image` with an `image_url` MUST become a chat `image_url` part with the same URL string, and a `function_call_output` whose output contains `input_image` parts MUST become a chat `tool` message whose content keeps those images as `image_url` parts in their original order. A tool output with only text MUST keep its current string form.

#### Scenario: Input image to a chat provider

- **WHEN** a Responses request for an OpenAI-compatible, OpenRouter or Claude model carries `{"type":"input_image","image_url":"data:image/png;base64,AAAA"}`
- **THEN** the provider receives `{"type":"image_url","image_url":{"url":"data:image/png;base64,AAAA"}}`

#### Scenario: Tool output with an image

- **WHEN** a `function_call_output` has output `[{"type":"input_text","text":"shot"},{"type":"input_image","image_url":"data:image/png;base64,AAAA"}]`
- **THEN** the provider receives a `tool` message with content `[{"type":"text","text":"shot"},{"type":"image_url","image_url":{"url":"data:image/png;base64,AAAA"}}]`

#### Scenario: Provider refuses the image

- **GIVEN** the chat provider answers a 4xx error about image input
- **WHEN** a client sends the Responses request
- **THEN** the client receives that status and error message and Codex receives nothing
