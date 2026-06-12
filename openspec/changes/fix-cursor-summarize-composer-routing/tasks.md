# Tasks

## 1. Summarize control payload policy

- [x] 1.1 Add a typed trace-summarize policy payload adapter for payloads with
      a usable model field.
- [x] 1.2 Apply model alias normalization, API-key enforcement, unsupported
      reasoning normalization, service-tier policy, and model-access validation
      for `POST /backend-api/codex/memories/trace_summarize`.
- [x] 1.3 Preserve trace-summarize-specific fields and keep other Codex control
      endpoints raw.

## 2. Verification

- [x] 2.1 Integration test: summarize rewrites Cursor GPT-5 aliases and
      enforced API-key policy before upstream dispatch.
- [x] 2.2 Integration test: summarize payloads without a model remain raw
      pass-through.
- [x] 2.3 Run targeted tests for the proxy API and request policy.
- [x] 2.4 Run `ruff` and `openspec validate fix-cursor-summarize-composer-routing --strict`.
