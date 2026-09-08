## Why

`GET /v1/models` only advertises configured sidecar full-model IDs. OpenRouter
and OrcaRouter show up because operators pin those IDs. CLIProxyAPI is used with
prefixes (`claude`, `cc/`) and an empty full-model list, so its discovered
Claude IDs never appear even when CLIProxyAPI is healthy and `/v1/models` there
returns them. Discovery-only clients therefore see OpenRouter/OrcaRouter but not
CLIProxyAPI.

## What Changes

- When CLIProxyAPI is enabled, advertise discovered CLIProxyAPI model IDs on
  `GET /v1/models` in addition to configured full models.
- Keep the unified resolver as the gate: a discovered ID is advertised only when
  it would route to CLIProxyAPI (prefix or full-model match). Unrelated IDs
  CLIProxyAPI may list (for example Gemini) stay out of the catalog unless they
  are also pinned as full models.
- Do not change OpenRouter, OrcaRouter, Ollama, or OmniRoute advertising.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `model-catalog-compat`: CLIProxyAPI discovered models that the resolver owns
  MUST appear on `GET /v1/models`

## Impact

- Code: `app/modules/proxy/api.py`
- Tests: `tests/integration/test_claude_sidecar_routing.py`
- Live: requires `codex-lb.service` restart to pick up the catalog change
