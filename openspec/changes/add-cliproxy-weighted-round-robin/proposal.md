# Add CLIProxyAPI Weighted Round Robin

## Why

CLIProxyAPI 7.2.135+ supports `weighted-round-robin` (per-credential integer `weight`, default 1). Operators can already set it in `config.yaml`, but the dashboard routing dropdown and `PUT /api/claude-sidecar/routing/strategy` only accept `round_robin` and `fill_first`. A live WRR value therefore shows as an empty strategy and choosing Fill first in Settings overwrites it.

## What Changes

- Accept `weighted_round_robin` on the CLIProxyAPI routing read/update API and map it to CLIProxyAPI's wire value `weighted-round-robin`.
- Add Weighted round robin to the CLIProxyAPI routing-strategy dropdown.
- Keep CLIProxyAPI auth-file `weight` as the source of truth; this change does not add weight editors.

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `dashboard-sidecar-management`: allow `weighted_round_robin` on routing GET/PUT and map it to `weighted-round-robin`.
- `frontend-architecture`: CLIProxyAPI routing dropdown includes Weighted round robin.

## Impact

- Affected backend: `app/modules/claude_sidecar/schemas.py`, `app/modules/claude_sidecar/service.py`
- Affected frontend: `frontend/src/features/settings/schemas.ts`, `frontend/src/features/settings/components/sidecar-integration-card.tsx`
- No migrations. No request-path routing changes (CLIProxyAPI still selects Claude auths).
