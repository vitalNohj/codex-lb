# Tasks

## 1. Specs

- [x] 1.1 Add the model-catalog-compat delta: CLIProxyAPI discovered models that the sidecar resolver owns MUST appear on `GET /v1/models`.

## 2. Catalog advertising

- [x] 2.1 Include CLIProxyAPI discovered model IDs alongside configured full models when building the OpenAI-compatible catalog.
- [x] 2.2 Keep the unified resolver filter so a discovered ID is advertised only when it would route to CLIProxyAPI.

## 3. Tests

- [x] 3.1 Integration: enabled CLIProxyAPI with empty full models advertises discovered `claude-*` IDs and omits a discovered ID that does not match a CLIProxyAPI prefix.
- [x] 3.2 Run `openspec validate advertise-cliproxy-discovered-models --strict` and the Claude sidecar `/v1/models` tests.
