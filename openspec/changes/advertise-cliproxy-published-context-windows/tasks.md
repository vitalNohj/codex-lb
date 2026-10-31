## 1. Read CLIProxyAPI's published limits

- [x] 1.1 Verify the Codex-client catalog shape against CLIProxyAPI v8.0.36 (`{"models":[{slug, context_window, max_context_window, max_tokens, visibility, ...}]}`; `slug` equals the plain listing id) and record fixtures from it.
- [x] 1.2 `ClaudeSidecarClient.list_published_model_limits()`: fetch `GET /v1/models?client_version=<CODEX_VERSION>`, keep rows with positive `context_window` and `max_tokens`, bounded timeout.
- [x] 1.3 Cache the limits per endpoint for the models cache TTL; keep last good on failure; empty on first failure.
- [x] 1.4 `list_models_cached()` fetches listing and limits concurrently and attaches limits by exact id; any catalog failure leaves the listing unchanged.

## 2. Advertise them

- [x] 2.1 `_sidecar_context_window`: override -> CLIProxyAPI-published -> Claude table -> provider catalog -> 200,000.
- [x] 2.2 Discovered ids and `cc/` strip-prefix aliases use the upstream id's published window and output limit.
- [x] 2.3 Advertise `max_output_tokens` / `maxOutputTokens` / `capabilities.max_output_tokens` only when published.

## 3. Regression coverage

- [x] 3.1 Unit: id mapping incl. `lb<hash>/` ids, placeholder rows ignored, listing unchanged, failure modes (HTTP error, bad body, timeout, transport, unexpected error), TTL cache across clients, per-endpoint cache, last-good on refresh failure, bounded timeout.
- [x] 3.2 Integration: `/v1/models` for grok-4.7, `cc/grok-4.7-build-fast`, `lb<hash>/` alias, image model, Claude models, and dashboard override precedence.
- [x] 3.3 Existing sidecar and `/v1/models` suites stay green.

## 4. Validation

- [x] 4.1 `openspec validate advertise-cliproxy-published-context-windows --strict`
