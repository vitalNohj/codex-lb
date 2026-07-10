# Design: Preserve Responses Lite Additional Tools

## Approach

Two complementary guards in `_normalize_responses_input_instructions`:

1. **Lite early-return** (upstream #1161): if any input item has `type == "additional_tools"`, return the payload unchanged. This keeps the Lite prefix (tools + adjacent developer instructions) in wire order instead of lifting the developer message into top-level `instructions`.

2. **Non-message pass-through** (upstream #1159): during the hoist loop, only hoist items whose `type` is omitted or `"message"`. Any other `system`/`developer`-role item is appended to `input` unchanged. Defends against other non-message directive shapes and against Lite payloads that somehow skip the early-return path.

Both `ResponsesRequest` and `ResponsesCompactRequest` share this normalizer, so one change covers HTTP, `/v1/responses`, websocket, and compact paths.

## Why not full #1161?

Upstream #1161 also synthesizes `x-openai-internal-codex-responses-lite` from body shape after #1099 started stripping the inbound header. Our 1.20.1-based fork never merged #1099, so inbound Lite headers still forward via `_build_upstream_headers`. The tools-drop bug is entirely the normalizer; header synthesis is deferred to a full upstream merge.

## Risks

- Low: early-return only triggers on the explicit Lite marker type.
- Existing message-hoisting tests for typeless/`message` system/developer items remain unchanged.
