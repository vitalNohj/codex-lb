## Why

DeepSeek V4 thinking-mode tool calls are unstable in Cursor-compatible clients because DeepSeek requires prior assistant `reasoning_content` to be passed back with tool-call history, while Cursor does not reliably echo that field. codex-lb already owns the OpenAI-compatible sidecar dispatch path for DeepSeek-family models, so it should repair this provider-specific gap before requests leave the proxy.

## What Changes

- Add DeepSeek V4-specific chat-completions compatibility for `deepseek-v4-pro` and `deepseek-v4-flash` traffic routed through OpenRouter or OmniRoute sidecar dispatch.
- Cache upstream DeepSeek assistant `reasoning_content` from non-streaming and streaming chat-completions responses when the assistant message participates in tool-call context.
- Patch missing `reasoning_content` back into later outgoing assistant tool-call messages for the same logical conversation/tool-call history.
- Preserve model/account isolation for cached reasoning so unrelated conversations, configured providers, API keys, and model families cannot reuse each other's reasoning content.
- Normalize only the DeepSeek V4 sidecar payload details needed for compatibility, such as reasoning-effort aliases and legacy function/tool fields, without changing native Codex routing.
- Keep Cursor-visible reasoning display optional and provider-scoped; the required behavior is repairing the wire payload, not exposing hidden reasoning in the dashboard.

## Non-goals

- Do not route native Codex, Claude/CLIProxyAPI, non-DeepSeek OpenRouter, or non-DeepSeek OmniRoute models through this compatibility adapter.
- Do not add a new dashboard integration card or new provider account type for DeepSeek.
- Do not manage DeepSeek API keys directly outside the existing sidecar provider configuration.
- Do not alter `/backend-api/codex/models`, Codex control endpoints, or Responses API routing.
- Do not guarantee recovery when a user imports an old conversation whose required DeepSeek reasoning was never observed by codex-lb.

## Capabilities

### New Capabilities

### Modified Capabilities

- `chat-completions-compat`: DeepSeek V4 sidecar chat-completions requests repair missing `reasoning_content` for tool-call history while preserving existing OpenAI-compatible streaming, non-streaming, error, and Cursor usage semantics.

## Impact

- Sidecar chat dispatch in `app/modules/proxy/openrouter_sidecar_dispatch.py` and `app/modules/proxy/omniroute_sidecar_dispatch.py`.
- Chat completions routing in `app/modules/proxy/api.py` for model/provider detection and adapter scoping.
- New provider-specific request/response transform helpers for DeepSeek V4 reasoning repair.
- Runtime storage for cached reasoning content, with bounded retention and collision-resistant keys.
- Unit and integration tests for non-streaming repair, streaming repair, provider/model isolation, missing-cache behavior, Cursor usage fallback compatibility, and non-DeepSeek pass-through.
