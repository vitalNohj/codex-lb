## Why

Clients pick models from `GET /v1/models`. A Claude strip prefix such as `cc/` is how those clients name a CLIProxyAPI model, but the catalog only keeps an id when dispatch sends that exact string. `cc/claude-opus-5-5` is forwarded as `claude-opus-5-5`, so the prefixed id never appears, while the bare pinned id does.

## What Changes

- List a Claude strip-prefix alias on `GET /v1/models` when dispatch of that alias returns the upstream id the alias names
- Keep hiding an alias whose model profile rewrites the upstream id to something else
- Leave bare discovered ids that do not themselves route off the catalog

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `model-catalog-compat`: `GET /v1/models` MUST advertise Claude strip-prefix aliases that dispatch to the named upstream id

## Impact

- Code: `app/modules/proxy/api.py` catalog builder
- Tests: Claude sidecar `/v1/models` listing and a chat round trip for `cc/claude-opus-5-5`
- Live: a `codex-lb.service` restart is required before clients see the new ids
