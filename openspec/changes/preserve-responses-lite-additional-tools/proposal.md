# Preserve Responses Lite Additional Tools

## Summary

Stop dropping Codex Responses Lite `additional_tools` input items during instruction-hoisting normalization so GPT-5.6 sessions keep their shell/filesystem tools.

## Motivation

Codex clients for GPT-5.6 (`use_responses_lite=true`, `tool_mode=code_mode_only`) do not send a top-level `tools` array. Tool definitions arrive as the first `input` item:

```json
{"type": "additional_tools", "role": "developer", "tools": [{"type": "custom", "name": "exec"}, ...]}
```

`_normalize_responses_input_instructions()` treats every `system`/`developer`-role input item as an instruction message. `additional_tools` has no `content`, so it contributes no instruction text and is removed from `input`. Upstream then receives a well-formed request with no tools, and the model answers that no shell/filesystem tool is available.

This is upstream Soju06/codex-lb #1157 / #1161 / #1159. Our fork is based on 1.20.1 and does not yet include those merges; a full upstream merge has ~40 conflict files, so this change backports the normalizer fix surgically.

## Scope

- When `input` contains an `additional_tools` item, leave the entire `input` array and top-level `instructions` unchanged (preserve the native Lite wire shape).
- When hoisting, only lift actual message items (`type` omitted or `"message"`); pass other `system`/`developer`-role items through untouched.
- Apply to both `ResponsesRequest` and `ResponsesCompactRequest`.
- Add regression coverage for the Lite prefix.

## Out of Scope

- Full upstream merge of #1161 Lite header synthesis / websocket continuity (follow-up; our fork does not strip the Lite header today, so client-sent signaling still forwards).
- GPT-5.6 bootstrap catalog / pricing (#1176) — separate change.
- Modeling the `additional_tools` schema; forward opaquely.
