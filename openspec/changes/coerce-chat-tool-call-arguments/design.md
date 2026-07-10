# Design: Coerce Chat Tool-Call Arguments

## Approach

In `_decompose_assistant_tool_calls`, when `function.arguments` is not a string:

- `None` / missing → `"{}"`
- `dict` / `list` / other JSON-serializable values → `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`
- Keep rejecting only if serialization fails (should not happen for inbound JSON).

In `openai_client_payload_error`, when the exception has no custom `code`/`error_type`, still return an invalid_request envelope but use `str(exc)` as `message` when non-empty, keeping `param`.

## Alternatives

- Reject with a clearer message only: helps diagnosis but leaves Cursor broken.
- Coerce only for Cursor user-agents: fragile; object arguments are a general OpenAI-compat quirk.

## Risks

- Clients that accidentally send malformed argument objects get silently stringified instead of 400. Acceptable for a proxy; upstream still validates tool schemas.
