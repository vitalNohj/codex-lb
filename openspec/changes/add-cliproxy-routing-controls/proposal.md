# Add CLIProxyAPI Routing Controls

## Why

Operators need to change CLIProxyAPI's Claude-account selection behavior without restarting CLIProxyAPI or editing its files by hand. CLIProxyAPI already exposes runtime Management API endpoints for reading/updating the routing strategy and patching auth-file priority metadata, but codex-lb only surfaces sidecar status, models, quota, and stored settings.

Adding these controls to the existing CLIProxyAPI integration card lets operators switch between round-robin and fill-first routing and adjust which Claude account is preferred at runtime while keeping CLIProxyAPI as the source of truth.

## What Changes

- Add dashboard endpoints under `/api/claude-sidecar` to read live routing state, update the routing strategy, and update a single auth file's priority through CLIProxyAPI's Management API.
- Add `ClaudeSidecarClient` Management API helpers for `GET /v0/management/routing/strategy`, `PUT /v0/management/routing/strategy`, and `PATCH /v0/management/auth-files/fields`.
- Add Settings UI controls in the CLIProxyAPI integration card: a strategy dropdown for `round_robin` / `fill_first` and per-account numeric priority inputs.
- Keep CLIProxyAPI's `config.yaml` and auth-file metadata as the only source of truth; codex-lb does not add database columns or cache a separate desired routing state.

## Impact

- Affected specs: `dashboard-sidecar-management`, `frontend-architecture`
- Affected backend code: `app/core/clients/claude_sidecar.py`, `app/modules/claude_sidecar/schemas.py`, `app/modules/claude_sidecar/service.py`, `app/modules/claude_sidecar/api.py`
- Affected frontend code: `frontend/src/features/settings/schemas.ts`, `frontend/src/features/settings/api.ts`, `frontend/src/features/settings/hooks/use-settings.ts`, `frontend/src/features/settings/components/sidecar-integration-card.tsx`, `frontend/src/features/settings/components/claude-sidecar-settings.tsx`
- No migrations or service restarts are required.
