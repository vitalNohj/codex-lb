## Why

`GET /v1/models` advertises `context_length: 200000` for every xAI model that CLIProxyAPI serves, including `grok-4.7` and `grok-4.7-build-fast` (500,000-token windows) and `grok-4.20-*` (2,000,000). codex-lb lists CLIProxyAPI models through its plain OpenAI `GET /v1/models`, which keeps only `id`, `object`, `created` and `owned_by`, so the catalog layer of `advertise-real-sidecar-context-windows` has nothing to read and every non-Claude model falls through to the 200k placeholder. Clients that size compaction from the advertised window (Cursor, Pi, nohjbot) therefore treat a 500k Grok model as a 200k one.

CLIProxyAPI already knows the real limits. Its Codex-client catalog (`GET /v1/models?client_version=...`, the same route) publishes `context_window` and `max_tokens` for each id the plain listing returns, `lb<hash>/` auth-prefixed ids included. The static Claude table in codex-lb also disagrees with CLIProxyAPI for at least one model (`claude-sonnet-4-6`: table 1M, CLIProxyAPI 200k), and CLIProxyAPI is the component that actually serves the request.

## What Changes

- The Claude sidecar listing also fetches CLIProxyAPI's Codex-client catalog, concurrently with the plain listing, and attaches each id's published `context_window` and `max_tokens` to its `SidecarModel`.
- A catalog row counts only when it has both a positive `context_window` and a positive `max_tokens`. CLIProxyAPI emits `max_tokens` only from a model's real registry limit, while image, video and TTS ids carry the catalog template's placeholder `context_window` (272000) and no `max_tokens`; those publish nothing.
- Window resolution for Claude-sidecar entries becomes: operator override for the advertised id; the CLIProxyAPI-published window for the upstream id; the Claude table; the provider catalog entry; 200,000. A `cc/` strip-prefix alias uses the row of the upstream id it names.
- Entries with a published output limit also advertise `max_output_tokens`, `maxOutputTokens` and `capabilities.max_output_tokens`, the fields registry models already use. Entries without one omit them.
- The catalog is cached per sidecar endpoint (base URL and API key) for `claude_sidecar_models_cache_ttl_seconds`, outside the per-request client. A failed refresh keeps the last good limits; with none, or on any catalog error or timeout (bounded at 10 s or the request timeout, whichever is lower), the listing is returned unchanged with today's windows.
- No new setting, no migration, no dashboard change. Which models are listed, routing, pricing and admission are unchanged. The management API is not used.

## Capabilities

### Modified Capabilities

- `model-catalog-compat`: Claude-sidecar (CLIProxyAPI) entries on `/v1/models` advertise the context window and output limit CLIProxyAPI publishes.

## Impact

- Code: `app/core/clients/claude_sidecar.py` (catalog fetch, cache, enrichment), `app/modules/proxy/api.py` (window precedence and output-limit fields for Claude-sidecar rows).
- Tests: `tests/unit/test_claude_sidecar_published_limits.py` with CLIProxyAPI v8.0.36 fixtures (`tests/fixtures/cliproxy_v8_0_36_*.json`), `tests/integration/test_claude_sidecar_routing.py`.
- One extra request to CLIProxyAPI per cache TTL (default 60 s); the response is about 200 KB for 78 models.
