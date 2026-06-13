# Tasks

## 1. Revert control endpoint to raw pass-through

- [x] 1.1 Make `codex_memories_trace_summarize` call `_codex_control_proxy`
      with no payload override, matching upstream.
- [x] 1.2 Delete `_trace_summarize_control_payload` and
      `_TraceSummarizePolicyPayload`.
- [x] 1.3 Remove the `payload_override` parameter from `_codex_control_proxy`
      and restore the upstream body read.
- [x] 1.4 Remove imports left unused by the revert (`json`, pydantic
      `BaseModel`/`ConfigDict`/`Field`/`field_validator`, `ResponsesReasoning`).

## 2. Verification

- [x] 2.1 Delete the obsolete `tests/unit/test_proxy_trace_summarize.py`.
- [x] 2.2 Replace the policy-injection integration test with one asserting a
      GPT-5 alias summarize body is forwarded unchanged even under an enforcing
      API key.
- [x] 2.3 Keep the no-model raw pass-through and parametrized control-endpoint
      tests.
- [ ] 2.4 Run `ruff` and targeted proxy API tests, plus
      `openspec validate revert-cursor-summarize-control-passthrough --strict`.
