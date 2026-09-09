# Sanitize Cursor Chat → Responses Mapping

## Why

Cursor Composer hits native Codex through `POST /v1/chat/completions`, not
through `cursor_chat_compat.py`. That module only rewrites usage and
context-length compaction. The live `usage_limit_reached` pin happened because
the mapped Responses body failed `responses_payload_is_account_neutral_fresh_replay`,
so streaming retry bound the request to the exhausted seat as dispatch owner.

Typical Composer chat shapes that Codex already accepts still fail that checker:

- assistant `content: ""` next to `tool_calls` (OpenAI/Cursor default)
- structured `tool_choice: {"type": "auto"}`
- flat `name` + `input_schema` tool declarations
- leftover chat extras (`frequency_penalty`, `seed`, `logit_bias`, …)

A first turn with nested OpenAI tools and string `tool_choice: "auto"` is already
portable. Agent history and Cursor-native tool grammar are not. Sidecar dispatch
already normalizes the Cursor-native tool grammar; the native Codex mapping does
not.

This is not a new Cursor usage shim, a denylist, or a weakening of hard
previous-response / file / unpaired-tool ownership.

## What Changes

- Drop blank assistant content when decomposing chat `tool_calls` into Responses
  input, matching today's `content: null` path.
- Normalize structured `{"type":"auto"|"none"|"required"}` (and `"any"` →
  `"required"`) tool choice to the Responses string form.
- Lift Cursor-flat function tools (`name` + `input_schema`) onto the same
  `{type,name,description,parameters,strict}` shape the nested OpenAI path
  already emits. Keep unknown extra keys so account-scoped fields such as
  `container_id` still fail closed.
- Strip additional chat-only extras from forwarded Responses payloads so they
  cannot fail the dedicated-field allowlist.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `chat-completions-compat`
- `responses-api-compat`

## Impact

Native Codex `/v1/chat/completions` mapping only. Sidecar Cursor sanitization is
unchanged. Hard ownership and unpaired tool-call history stay fail-closed.
The pre-visible usage-exhaustion sticky failover is a separate change; this
makes ordinary Composer bodies portable for every pre-visible recovery class,
not only quota exhaustion.
