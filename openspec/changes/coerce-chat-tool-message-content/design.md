## Context

Chat `/v1/chat/completions` maps `role=tool` messages via `_convert_tool_message` into Responses `function_call_output` items. Today it concatenates text parts and raises `ClientPayloadError` when the array is non-empty but yields no text. The Responses input normalizer (`_normalize_tool_output_value`) and user `tool_result` helper (`_tool_result_output`) already fall back to compact JSON for non-text arrays. Cursor agent tool results often include image-only or empty text part arrays on BYOK chat, so mid-conversation GPT-5.6 turns fail with the exact provider error users see.

## Goals / Non-Goals

**Goals:**
- Align chat tool-message array coercion with Responses `_normalize_tool_output_value`.
- Accept empty-string text parts as valid empty output.
- Keep null / wrong-type content rejected.

**Non-Goals:**
- Multimodal Responses `function_call_output` (images stay JSON-serialized strings).
- Changing sidecar chat forwarding.
- Remapping `call_id` length.

## Decisions

1. **JSON fallback over reject** — When a tool content array has no string `text` fields, serialize with `json.dumps(..., separators=(",", ":"))` instead of raising. Matches Responses path; preserves enough structure for the model to see non-text tool output existed.
2. **Empty text parts → `""`** — If any part contributes a string `text` (including `""`), join those strings. Do not treat `[""]` as "no valid parts".
3. **Reuse local concat + fallback** — Keep logic in `message_coercion.py` next to `_convert_tool_message`; do not import from `requests.py` (avoids cycle / layering).

## Risks / Trade-offs

- [Image bytes in JSON] → Mitigation: same as Responses path today; large screenshots inflate tokens but request proceeds.
- [Malformed `{"type":"text"}` without text] → Mitigation: JSON-serialize whole array rather than invent empty string; model still sees the part.

## Migration Plan

Deploy with normal proxy restart. No DB/schema changes. Rollback = revert commit.

## Open Questions

None.
