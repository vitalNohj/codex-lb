## 1. Minimal output cap passthrough

- [x] 1.1 Forward a client `max_tokens` / `max_completion_tokens` of at most 16 unchanged in `apply_sidecar_max_tokens_bounds()`.
- [x] 1.2 Unit tests: 1 and 16 stay unchanged for both fields; 17 is still raised to the floor.

## 2. Validation

- [x] 2.1 `openspec validate keep-sidecar-cache-warm-output-cap --strict`.
- [x] 2.2 `uv run pytest tests/unit/test_claude_sidecar_dispatch.py`.
