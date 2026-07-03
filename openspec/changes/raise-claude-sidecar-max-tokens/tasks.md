## 1. Claude sidecar max_tokens floor/cap

- [x] 1.1 Add per-model output floor/cap table keyed by canonical Claude model in `claude_sidecar_dispatch.py` (Fable 5 / Opus 4.8: floor 32768, cap 128000; Haiku 4.5 / Sonnet 4.5: floor 32768, cap 64000).
- [x] 1.2 Apply `min(max(client, floor), cap)` to `max_tokens` (and `max_completion_tokens` when present) in `build_sidecar_chat_payload()` after the model profile resolves the wire model; no-op when the client sent no value or the model has no cap.
- [x] 1.3 Unit tests: 4096 raised to floor, above-floor value preserved, above-cap value clamped, absent value stays absent, unknown model unchanged, `max_completion_tokens` treated identically.

## 2. Validation

- [x] 2.1 `openspec validate raise-claude-sidecar-max-tokens --strict`.
- [x] 2.2 `uv run pytest tests/unit/test_claude_sidecar_dispatch.py`.
