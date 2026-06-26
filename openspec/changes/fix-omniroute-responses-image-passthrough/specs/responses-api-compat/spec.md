## MODIFIED Requirements

### Requirement: Translate Responses sidecar requests to chat-completions and back

For OmniRoute sidecar Responses requests, the service MUST build the chat-completions `messages` from the Responses `instructions` and `input` content, preserve user image content by emitting `input_image`/`image_url` input parts as OpenAI chat `image_url` content parts (never dropping them), forward `tools` and `tool_choice` in OpenAI chat-completions shape, and request usage by setting or preserving `stream_options.include_usage=true` when streaming. When an input item's content is text-only, the service MUST collapse it to a plain string; when the content includes image parts, the service MUST emit an OpenAI chat content-parts array preserving both text and image parts. The service MUST surface the OmniRoute assistant output to the downstream client as a Responses result (non-streaming) or Responses event stream (streaming). Codex-native server-side continuity fields (`previous_response_id`, `conversation`, `store`) MUST NOT cause Codex account state to be consulted for sidecar requests.

#### Scenario: Streaming Responses sidecar request emits Responses events

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"` and `stream: true`
- **AND** OmniRoute returns OpenAI-compatible chat-completion SSE deltas
- **THEN** the downstream response is `text/event-stream`
- **AND** the stream begins with a `response.created` event
- **AND** the stream ends with a terminal `response.completed` event

#### Scenario: Non-streaming Responses sidecar request returns a Responses result

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"` and `stream: false`
- **AND** OmniRoute returns an OpenAI-compatible chat-completion JSON body
- **THEN** the downstream response is a Responses result object containing the assistant output

#### Scenario: Input image is preserved when translating to chat-completions

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"` and a user input item whose content includes an `input_text` part and an `input_image` part with an image data URL
- **THEN** the forwarded OmniRoute `/chat/completions` request's user message `content` is an array
- **AND** the array includes a `text` part with the input text
- **AND** the array includes an `image_url` part whose `image_url.url` equals the input image data URL

#### Scenario: Text-only input collapses to a string

- **GIVEN** `omniroute_sidecar_enabled=true`
- **AND** the OmniRoute sidecar selected model list includes `my-selected-model`
- **WHEN** a client sends `POST /v1/responses` with `model: "my-selected-model"` and a user input item whose content is text-only
- **THEN** the forwarded OmniRoute `/chat/completions` request's user message `content` is a plain string
