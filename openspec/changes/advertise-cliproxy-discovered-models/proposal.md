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
- Require a discovered ID to equal the model dispatch would actually request.
  Two rewrites sit in between: the resolver strips a matched `strip` prefix
  (`cp-claude-sonnet` becomes `claude-sonnet`), and the dispatch-time model
  profile maps aliases and splits a reasoning-effort suffix (`claude-fable-5-1`
  becomes `claude-fable-5`). Advertising an ID that either rewrite changes would
  send the client to a different model than the catalog named, so such IDs stay
  out of the catalog. Pinned full models are exempt and keep advertising exactly
  as before.
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
