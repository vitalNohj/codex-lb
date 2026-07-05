## 1. Claude sidecar max_tokens floor/cap

- [x] 1.1 Add per-model output `(floor, cap, context_window)` table keyed by canonical Claude model in `claude_sidecar_dispatch.py`, using the authoritative Anthropic limits cross-checked against OmniRoute's model-capability registry (Fable 5 / Opus 4.6–4.8 / Sonnet 5: cap 128000; Sonnet 4.5/4.6, Haiku 4.5: cap 64000; Opus 4.5: cap 32768; floor 32768).
- [x] 1.2 Apply `min(max(client, floor), cap)` to `max_tokens` (and `max_completion_tokens` when present) in `build_sidecar_chat_payload()` after the model profile resolves the wire model; no-op when the client sent no value or the model has no bounds.
- [x] 1.3 Add a context-window guard: estimate input tokens from the serialized messages and lower a raise so `input + max_tokens` fits the model window, but never below the client's original value (prevents 200k-context-model 400s).
- [x] 1.4 Unit tests: 4096 raised to floor across all thinking models, above-floor preserved, above-cap clamped, absent stays absent, unknown model unchanged, `max_completion_tokens` identical, context-window guard lowers the raise, guard never drops below client, large-window model ignores input size.

## 2. Validation

- [x] 2.1 `openspec validate raise-claude-sidecar-max-tokens --strict`.
- [x] 2.2 `uv run pytest tests/unit/test_claude_sidecar_dispatch.py`.
