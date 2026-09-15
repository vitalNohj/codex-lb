## Why

Anthropic rejects two message shapes that OpenAI-compatible agent frameworks (n8n, Frappe Flow, LangChain-based nodes) routinely send after an aborted or timed-out tool loop:

- an assistant `tool_calls` turn with no `tool` message for one or more of its call ids (`messages.N: tool_use ids were found without tool_result blocks immediately after`), and
- a `tools` array that lists the same function name twice (`tools: Tool names must be unique.`).

CLIProxyAPI forwards both as-is to Anthropic, so the Claude sidecar path returns a 400 for the whole conversation and the client's agent loop dies. Both were observed in production request logs from the Flow integration. Other routers that front Anthropic (LiteLLM, OpenRouter) repair these shapes before forwarding.

## What Changes

- The Claude sidecar chat payload builder inserts a placeholder `tool` message for every assistant `tool_calls` id that has no matching `tool` message before the next non-tool message, immediately after that assistant turn.
- The Claude sidecar chat payload builder drops later tool definitions whose function name duplicates an earlier one, keeping the first definition.
- No change to OpenRouter, OmniRoute, OrcaRouter, Ollama, or native Codex paths.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `chat-completions-compat`: Claude sidecar forwarding repairs unanswered `tool_calls` and duplicate tool names before the payload leaves codex-lb.

## Impact

- Backend: `app/modules/proxy/claude_sidecar_dispatch.py` (message sanitization), `app/modules/proxy/sidecar_tool_mapper.py` (tool definition dedupe).
- Tests: unit coverage on both helpers, route-level regression on `/v1/chat/completions` proving the forwarded sidecar payload is repaired.
- No schema, settings, or API surface changes.
