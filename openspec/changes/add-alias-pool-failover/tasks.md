## 1. Pool data model and settings

- [x] 1.1 Add `ModelAliasPool` (`targets: tuple[str, ...]`) and make `parse_model_aliases` return `dict[str, ModelAliasPool]`, accepting both the legacy string value and the pool object.
- [x] 1.2 Add `ModelAliasPoolSchema` to `app/modules/settings/schemas.py`; accept `str | ModelAliasPoolSchema` on write, normalize to the pool shape, keep the 256-char caps, add the 16-target cap.
- [x] 1.3 Add pool validation to `SettingsService` (empty, duplicate, alias-as-target, non-pool-capable member of a 2+ pool, native Codex member of a 2+ pool) using the enabled routing entries; surface as the existing settings validation error with alias and target named.
- [x] 1.4 Define `POOL_CAPABLE_PROVIDERS = {"orcarouter", "openrouter"}` plus the `openai_compat:` prefix check in `app/modules/proxy/alias_pool_dispatch.py`.
- [x] 1.5 Alembic revision parented on `20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads` (the live head after rebase): normalize `model_aliases_json` values, add `request_logs.upstream_model` and `request_logs.pool_attempts`, idempotent upgrade, downgrade truncates to `targets[0]` and drops only the two columns.
- [x] 1.6 Add `upstream_model` and `pool_attempts` to `RequestLog`, the request-log write path, and the dashboard request-log row schema.

## 2. Resolution and catalog

- [x] 2.1 Change `resolve_model_alias` to return `tuple[str, ...]`; `resolve_request_model_alias` returns the tuple and logs `targets=<n>`; Responses hooks take `[0]`.
- [x] 2.2 Update `build_discoverable_alias_model_entries` to clone the first present target and list the alias when any target is visible; keep `custom_alias_catalog` overlays working.

## 3. Open-before-commit split (pool-capable providers)

- [x] 3.1 OrcaRouter: add `open_chat` (performs the POST, raises `OrcaRouterSidecarError` on >= 400, returns an opened stream owned by an `AsyncExitStack`, or the non-streaming JSON body) and `stream_opened`; `proxy_chat_to_orcarouter` uses them.
- [x] 3.2 OpenRouter: same split.
- [x] 3.3 OpenAI-compat endpoints: same split.
- [x] 3.4 Ensure the exit stack closes on iterator completion, on client disconnect, and when the iterator is never started (early error).
- [x] 3.5 Verify streaming upstream 4xx/5xx now returns a JSON error with the upstream status before any SSE bytes, on the unaliased path.

## 4. Failover loop

- [x] 4.1 Implement `dispatch_chat_with_failover` in `alias_pool_dispatch.py`: ordered attempts, per-target access check, cooldown skip with soonest-to-expire fallback, `request.is_disconnected()` check between attempts, `alias_pool_attempt` log line per attempt.
- [x] 4.2 Implement retryable classification for the three providers' error types (transport, 401/402/403/408/429/5xx retryable; everything else and the cursor-compat context-length case non-retryable).
- [x] 4.2a Keep the provider's one-shot same-target retry (`retry-orcarouter-provider-failure`) inside each attempt: a 5xx or transport open failure is retried once on the target before the loop classifies it, and a stream that fails before its first chunk shares that one retry through `open_sidecar_stream` / `relay_sidecar_stream`.
- [x] 4.3 Implement the process-local cooldown registry keyed by target string (402 -> 30 min, 429 -> `Retry-After` capped at 1 h else 60 s, other -> 60 s; success clears).
- [x] 4.4 Return the last attempt's client-facing error with `X-Codex-LB-Pool-Attempts` on total failure.
- [x] 4.5 Wire `v1_chat_completions`: validate access on the alias, reserve once against the alias, then call the loop for 2+ targets or the shared single-target dispatch otherwise. Keep `payload.model` as the alias for metering; pass the target as the model to resolve and forward.
- [x] 4.6 Thread `upstream_model`, `pool_attempts`, and accumulated failover time (`latency_queue_ms`) into the three providers' request-log writers.
- [x] 4.7 Confirm cost resolution uses the serving target's provider and effective model, not the alias.

## 5. Health endpoint and dashboard

- [x] 5.1 Add `GET /api/settings/alias-pools/health` (dashboard auth) reading the cooldown registry.
- [x] 5.2 Frontend: zod `modelAliases` becomes `Record<string, { targets: string[] }>`; payload builder sends the pool shape; hooks updated.
- [x] 5.3 Frontend: `ModelAliasRow` renders an ordered chip list with add (datalist), remove (disabled on last), move up/down; row-level Remove deletes the alias; keep the Advanced context-length control.
- [x] 5.4 Frontend: inline server validation error on the offending row without discarding the unsaved list.
- [x] 5.5 Frontend: poll health every 15 s while mounted and render chip states; stop on unmount.
- [x] 5.6 Before/after screenshots of the Routing alias section for the PR.

## 6. Tests

- [x] 6.1 Unit: alias parsing (both shapes), validation rules, retryable classification table, cooldown expiry and soonest-to-expire, catalog entry building with partially visible targets.
- [x] 6.2 Integration with fake upstreams: 402 then 200 (streaming and non-streaming); 400 returned without second call; cursor context-length synthetic success without second call; disallowed first target skipped; all targets fail returns last error and attempts header; log row `model=alias`, `upstream_model`, `pool_attempts`; single reservation finalized once.
- [x] 6.3 Integration: unaliased OrcaRouter/OpenRouter/openai-compat streaming upstream 502 yields a JSON 502, no SSE bytes.
- [x] 6.4 Migration tests: string to pool, idempotent on pool rows, downgrade truncation, single head.
- [x] 6.5 Frontend tests: reorder/add/remove targets, last-target remove disabled, health chip states, poll lifecycle.

## 7. Docs and validation

- [x] 7.1 Add `docs/alias-pools.md` (mkdocs) linking to `openspec/specs/alias-pool-routing/`; no new README section (PRINCIPLES P3/P4).
- [x] 7.2 Run `openspec validate add-alias-pool-failover --strict`, `uv run pre-commit run local-ci --hook-stage manual --all-files`, and the frontend test suite.
