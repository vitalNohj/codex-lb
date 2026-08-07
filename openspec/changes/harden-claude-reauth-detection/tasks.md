## 1. Mapping harden

- [x] 1.1 Narrow `_looks_like_reauth` so generic `status=error` no longer maps to `reauth_required`; keep message substrings and `unavailable` + `unauthorized`
- [x] 1.2 Add unit regression: `context canceled` / `unavailable` / `error` stays non-reauth
- [x] 1.3 Keep existing unit coverage for `authentication_error` and blank-message `unauthorized` → `reauth_required`

## 2. Verify

- [x] 2.1 Run `openspec validate harden-claude-reauth-detection --strict`
- [x] 2.2 Run `uv run pytest tests/unit/test_sidecar_account_summaries.py`
