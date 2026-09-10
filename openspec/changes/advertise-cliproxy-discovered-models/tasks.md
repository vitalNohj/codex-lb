# Tasks

## 1. Specs

- [x] 1.1 Add the model-catalog-compat delta: CLIProxyAPI discovered models that the sidecar resolver owns MUST appear on `GET /v1/models`.

## 2. Catalog advertising

- [x] 2.1 Include CLIProxyAPI discovered model IDs alongside configured full models when building the OpenAI-compatible catalog.
- [x] 2.2 Keep the unified resolver filter so a discovered ID is advertised only when it would route to CLIProxyAPI.
- [x] 2.3 Advertise a discovered ID only when it survives both dispatch rewrites - the resolver's `strip` prefix removal and the dispatch-time model profile (alias mapping plus reasoning-effort suffix split) - so the advertised ID always equals the dispatched wire model. Pinned full models are exempt and keep their existing advertising.

## 3. Tests

- [x] 3.1 Integration: enabled CLIProxyAPI with empty full models advertises discovered `claude-*` IDs and omits a discovered ID that does not match a CLIProxyAPI prefix.
- [x] 3.2 Integration: read `GET /v1/models` and dispatch every advertised ID back through the request path, asserting the wire model equals the advertised ID, with discovered IDs rewritten by the prefix strip and by the model profile both omitted; and pinned IDs under a `strip` prefix and under a profile rewrite both stay advertised.
- [x] 3.3 Run `openspec validate advertise-cliproxy-discovered-models --strict` and the Claude sidecar `/v1/models` tests.
