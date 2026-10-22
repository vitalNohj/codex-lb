## Why

codex-lb is a router. A request that carries images must reach the provider
that owns the model with its image parts intact, and when that provider cannot
take images, the provider's own error must reach the client. Production showed
two ways the router broke that rule:

- A model id that no external route owns (for example
  `nvidia/nemotron-3.5-content-safety:free` or `nvidia/nemotron-3-content-safety`)
  fell through `/v1/chat/completions` to the Codex upstream, which answered
  "The '<model>' model is not supported when using Codex with a ChatGPT
  account." after codex-lb had also replayed it on a second account. The client
  saw a misleading ChatGPT-account error instead of "this model does not exist".
  `/v1/responses` already answered `model_not_found` for such ids; chat did not.
- Image parts were silently removed or flattened on several paths:
  - chat requests mapped to Codex dropped any data-URL image larger than 8 MiB;
  - tool results carrying images (chat `tool` messages and Anthropic
    `tool_result` blocks) kept only their text on the Codex and Claude paths,
    and an image-only chat tool result was refused with a 400;
  - Responses `function_call_output` images sent to chat providers were turned
    into JSON text;
  - the Ollama dispatcher kept only message text, dropping every image;
  - a string-form `image_url` part was refused before routing.

## What Changes

- `/v1/chat/completions` answers 404 `model_not_found` naming the model, before
  quota reservation and without contacting Codex, when no external route, no
  model source and no authoritative Codex catalog serves the model. Same rule
  `/v1/responses` already applies; a non-authoritative catalog stays permissive
  so genuine Codex models still route to Codex during cold start.
- Chat requests no longer drop oversized images; the provider decides.
- Tool results with images keep their images: chat `tool` messages and
  Anthropic `tool_result` blocks map to a content-part `function_call_output`
  on Codex and to image parts on Claude (CLIProxyAPI); Responses
  `function_call_output` images map to chat `image_url` parts for chat
  providers. Text-only tool results keep their current string form, so text
  requests are byte-identical and keep their cache prefix.
- Ollama receives data-URL images in the message `images` field. An image URL
  that is not a data URL is answered with a 400 naming the part, because the
  Ollama chat API only takes inline images.
- String-form `image_url` parts are accepted on chat.

## What Stays

- Routing never looks at image content; vision flags only feed `/v1/models`.
- Codex path behavior that mirrors the real Codex client: https image URLs are
  inlined as data URLs when `image_inline_fetch_enabled` is on (same image, and
  the URL is kept on fetch failure), historical images in an over-budget
  websocket `response.create` are slimmed, and image requests use the HTTP
  transport.
- `input_image` with only a `file_id` (or a `sediment://` reference) is still
  rejected with a 400: a chat provider has no way to resolve the reference.
- Provider 4xx errors pass through unchanged and are not retried on another
  provider or on Codex; alias-pool failover keeps its existing status list.

## Capabilities

### Modified Capabilities

- `chat-completions-compat`: unowned model ids, image pass-through, tool-result images.
- `responses-api-compat`: tool-output images for chat providers.
