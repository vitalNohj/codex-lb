## MODIFIED Requirements

### Requirement: Large image inputs are handled per OpenAI limits

The service MUST forward image inputs of any size unchanged to the provider that serves the model. It MUST NOT drop, shrink or rewrite an image because of its size; the provider's own limit and error apply.

#### Scenario: Oversized image input

- **GIVEN** a `user` message includes a data-URL image larger than 8MB
- **WHEN** the request is routed to Codex
- **THEN** the mapped Responses input still contains that image part unchanged

## ADDED Requirements

### Requirement: Chat requests for unowned models answer model_not_found

When `/v1/chat/completions` names a model that no external provider route, no model source and no authoritative Codex model catalog serves, the service MUST answer 404 with `code: "model_not_found"` and a message naming the model. It MUST answer before reserving API-key quota and MUST NOT contact Codex. When the Codex catalog is not authoritative, the request MUST still go to Codex.

#### Scenario: Unowned model id

- **GIVEN** the Codex model catalog is authoritative and does not list `nvidia/nemotron-3.5-content-safety:free`
- **AND** no external route or model source owns that id
- **WHEN** a client posts a chat completion for it
- **THEN** the service answers 404 `model_not_found` naming `nvidia/nemotron-3.5-content-safety:free`
- **AND** Codex receives nothing and no quota is reserved

#### Scenario: Codex model still routes

- **GIVEN** the Codex model catalog is authoritative and lists `gpt-5.4`
- **WHEN** a client posts a chat completion for `gpt-5.4`
- **THEN** the request is served by Codex

### Requirement: Chat image parts reach the provider unchanged

The service MUST NOT drop, refuse or reroute a chat request because it contains images. Image parts MUST reach the provider that owns the model with the same image URL or data URL bytes, and a provider's error about images MUST be returned to the client without retrying another provider or Codex.

#### Scenario: Image reaches an external provider

- **GIVEN** a model owned by an OpenAI-compatible endpoint, OpenRouter or Claude through CLIProxyAPI
- **WHEN** a user message carries an `image_url` part with a data URL or an https URL
- **THEN** the provider receives that part with the same URL string

#### Scenario: Provider refuses the image

- **GIVEN** the owning provider answers 404 "No endpoints found that support image input"
- **WHEN** a client sends an image request for that model
- **THEN** the client receives that status and error message
- **AND** no other provider and no Codex account is tried

#### Scenario: String-form image_url

- **WHEN** a user message carries `{"type": "image_url", "image_url": "<url>"}`
- **THEN** the service accepts the part and forwards the URL

### Requirement: Tool results keep their images

A chat `tool` message or an Anthropic `tool_result` block whose content includes images MUST keep those images. On Codex the result MUST map to a `function_call_output` whose `output` is a list of `input_text` and `input_image` parts in their original order. On Claude through CLIProxyAPI the tool message MUST keep its `image_url` parts. A tool result with only text MUST keep its current string form.

#### Scenario: Chat tool result with an image on Codex

- **WHEN** a chat `tool` message has content `[{"type":"text","text":"shot"},{"type":"image_url","image_url":{"url":"data:image/png;base64,AAAA"}}]`
- **THEN** the Codex request contains a `function_call_output` with output `[{"type":"input_text","text":"shot"},{"type":"input_image","image_url":"data:image/png;base64,AAAA"}]`

#### Scenario: Image-only tool result

- **WHEN** a chat `tool` message has only image parts
- **THEN** the request is accepted and the images are forwarded

#### Scenario: Text-only tool result

- **WHEN** a chat `tool` message has only text parts
- **THEN** the mapped `function_call_output.output` is the joined text string, as before

### Requirement: Ollama receives inline images

For a model served by Ollama, a data-URL image part MUST be sent in the Ollama message `images` field as its base64 payload. An image part whose URL is not a data URL MUST be answered with a 400 naming the part, because the Ollama chat API takes only inline images.

#### Scenario: Data-URL image to Ollama

- **WHEN** a user message for an Ollama model has text and a data-URL `image_url`
- **THEN** the Ollama message carries the text as `content` and the base64 payload in `images`

#### Scenario: Remote image URL to Ollama

- **WHEN** a user message for an Ollama model has an `image_url` with an https URL
- **THEN** the service answers 400 with `param` naming the content part and Ollama receives nothing
