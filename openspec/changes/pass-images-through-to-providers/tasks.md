## 1. Routing

- [ ] 1.1 Answer 404 `model_not_found` on `/v1/chat/completions` for a model no external route, model source or authoritative Codex catalog serves, before quota reservation.

## 2. Image pass-through

- [ ] 2.1 Stop dropping oversized data-URL images on the chat-to-Codex mapping.
- [ ] 2.2 Accept string-form `image_url` parts on chat.
- [ ] 2.3 Map chat `tool` messages and Anthropic `tool_result` blocks with images to content-part `function_call_output` on Codex; keep text-only results as strings.
- [ ] 2.4 Keep image parts in Anthropic `tool_result` blocks on the Claude (CLIProxyAPI) path.
- [ ] 2.5 Map Responses `function_call_output` images to chat `image_url` parts for chat providers.
- [ ] 2.6 Send data-URL images to Ollama in the message `images` field; reject other image URLs with a 400.

## 3. Verification

- [ ] 3.1 Unit tests for each mapping.
- [ ] 3.2 Integration tests: data-URL and https images reach OpenAI-compatible, OpenRouter, Claude and Codex byte-identical on chat and Responses; provider image errors pass through without fallback; unowned ids get `model_not_found`.
- [ ] 3.3 Local demo against stub upstreams and a before/after table from production request logs.
