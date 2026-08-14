## 1. Shared remapper

- [x] 1.1 Add `app/modules/proxy/sidecar_upstream_errors.py` with 401/403 → 503 + `Retry-After` + client-safe envelope helpers
- [x] 1.2 Unit-test remapper status, headers, and message rewrite (including `[401]: Missing API key`)

## 2. Wire into sidecar dispatches

- [x] 2.1 Apply remapper on OmniRoute chat non-stream + stream error paths
- [x] 2.2 Apply remapper on OmniRoute Responses sidecar error paths
- [x] 2.3 Apply remapper on OpenRouter, Claude, and Ollama chat dispatch error paths
- [x] 2.4 Keep request-log `error_message` as the original upstream text

## 3. Verification

- [x] 3.1 Unit/integration coverage that OmniRoute upstream 401 surfaces as client 503 + Retry-After
- [x] 3.2 `openspec validate remap-sidecar-upstream-auth-errors --strict`
- [x] 3.3 Run targeted pytest for remapper + OmniRoute dispatch
