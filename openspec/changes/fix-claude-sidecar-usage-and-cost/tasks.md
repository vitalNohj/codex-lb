# Tasks

## 1. OAuth usage retention in quota poller

- [x] 1.1 Pass the previous snapshot into `_classify_poll_result` /
      `_attach_oauth_usage` so a failed OAuth usage fetch reuses the
      last-known `oauth_usage` for the same auth identity.
- [x] 1.2 Unit tests: fetch failure retains prior bucket data; fetch success
      replaces it; new auths without prior data stay `None`.

## 2. Claude pricing

- [x] 2.1 Add Claude model entries (Fable 5, Opus 4.5-4.8, Sonnet 4/4.5/4.6,
      Sonnet 3.7, Haiku 3.5/4.5, Opus 4/4.1) to `DEFAULT_PRICING_MODELS`.
- [x] 2.2 Add alias patterns including date-suffixed ids
      (`claude-opus-4-5-*`) and prefix-tolerant patterns (`*claude-fable-5*`
      style) so sidecar-prefixed model ids resolve.
- [x] 2.3 Unit tests: `get_pricing_for_model` resolves `claude-sonnet-4-6`,
      `claude-opus-4-5-20251101`, and `cp-claude-fable-5`.

## 3. Cost backfill

- [x] 3.1 Alembic migration recomputing `cost_usd` for `request_logs` rows
      with `source='claude_sidecar'` and `cost_usd IS NULL` using the new
      pricing table.
- [x] 3.2 Migration test or manual verification that historical sidecar rows
      gain non-null `cost_usd`.

## 4. Verification

- [x] 4.1 Regression test at the dispatch/log path: a sidecar request log
      with a prefixed Claude model gets a non-null `cost_usd` at insert.
- [x] 4.2 `uv run pytest`, `uv run ruff check`, `openspec validate --strict`.
