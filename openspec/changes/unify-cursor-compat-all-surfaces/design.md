# Design

## One policy, two wire formats

Cursor compatibility stays a single concern with a single detector,
`is_cursor_compat_client`, in `app/modules/proxy/cursor_chat_compat.py`. The
detector is unchanged: an API key named `cursor`, or a user agent containing
`cursor`.

What was missing is not a second Cursor system but a second wire adapter. The
chat adapter already existed; this change adds the Responses adapter beside it
in the same module:

| Concern | Chat Completions | Responses |
| --- | --- | --- |
| Non-stream over-limit reply | `cursor_context_limit_usage_completion` | `cursor_context_limit_responses_completion` |
| Streaming over-limit reply | `cursor_context_limit_usage_stream` | `cursor_context_limit_responses_stream` |
| In-stream error rewrite | `CursorChatSseCompatRewriter` | `stream_responses_with_cursor_context_limit_fallback` |

Both adapters express the same rule: a context-length failure reaching a
Cursor-compatible client must arrive as a *successful* turn whose usage is at
or beyond the limit, because usage is the only signal Cursor compacts on.

## No model branching

Nothing in the Cursor layer inspects the model slug. The synthetic usage value
stays the existing `CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS`, so behavior
is identical for `gpt-5.2`, `gpt-5.5`, `gpt-5.6-sol`, and any model added
later. Regression tests are parametrized over several models with identical
assertions to keep it that way.

If a future model genuinely needs different handling, it belongs as a narrow,
named exception with a test proving why the shared rule is wrong for it, not as
a separate code path.

## Deliberate exclusions

**HTTP bridge internals.** The bridge owns session rollover, account health,
and reservation settlement around `context_length_exceeded`. Converting the
failure inside the bridge risks skipping that bookkeeping. The bridge continues
to raise exactly as before; the conversion happens at the API response
boundary, after the bridge has finished its own handling.

**Codex compact endpoints.** `responses/compact` and the Codex control
endpoints are raw pass-through. Injecting proxy-side rewrites there previously
broke Cursor's summarize flow, so they stay untouched.

**Successful turns.** Usage is only synthesized when the upstream actually
reports a context-length failure. Usage on successful responses is forwarded
unmodified so request logs, cost, and quota accounting stay truthful.

## Shared sidecar detection

`is_sidecar_context_length_error(body=..., message=...)` replaces the
Claude-only helper. All four sidecar error types expose the same
`status_code`/`message`/`body` shape, so one helper serves every provider and
no provider keeps its own Cursor logic.
