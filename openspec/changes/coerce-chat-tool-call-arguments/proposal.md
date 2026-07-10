# Coerce Chat Tool-Call Arguments

## Summary

Accept OpenAI-compatible chat `tool_calls[].function.arguments` that arrive as JSON objects (or other JSON values) by serializing them to strings before Responses mapping, and surface the real `ClientPayloadError` message in the OpenAI error envelope instead of a generic "Invalid request payload".

## Motivation

After the upstream model-use merge, Cursor BYOK `/v1/chat/completions` requests began failing with:

```json
{"error":{"message":"Invalid request payload","type":"invalid_request_error","code":"invalid_request_error","param":"messages"}}
```

That envelope is produced when `coerce_messages` raises `ClientPayloadError(param="messages")` and `openai_client_payload_error` discards the specific message. The matching failure mode is non-string `tool_calls[].function.arguments` (object/list/number/missing): chat request validation accepts the message, then coercion rejects it. Several OpenAI-compatible clients (including Cursor cloud relay paths) send arguments as objects rather than JSON strings.

## Scope

- Coerce non-string `tool_calls[].function.arguments` to a JSON string (`json.dumps`, missing → `"{}"`) during chat→Responses message coercion.
- Preserve specific `ClientPayloadError` text in the OpenAI error envelope (and logs) when `param` is set.
- Regression tests for object/missing arguments and envelope message preservation.

## Out of Scope

- Changing system/developer text-only rules.
- Remapping over-length `call_id` values.
- Sidecar dispatch paths (they already forward chat payloads without this coercion).
