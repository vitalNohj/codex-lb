# Add CLIProxyAPI Account Pause Toggle

## Why

Operators sometimes need to take one Claude account fully out of CLIProxyAPI rotation (for example, to force all traffic onto a preferred account) without deleting its auth file or editing JSON by hand. CLIProxyAPI already supports this via the `disabled` field on auth files, applied live by its file watcher, but codex-lb only exposes priority tuning, which cannot exclude an account outright.

Surfacing the `disabled` field as a "Pause"/"Resume" toggle in the existing routing controls, the Accounts tab, and the dashboard account card gives operators a one-click hard exclusion that CLIProxyAPI honors immediately.

## What Changes

- Add a dashboard endpoint `PUT /api/claude-sidecar/routing/paused` that patches an auth file's `disabled` field through CLIProxyAPI's Management API (`PATCH /v0/management/auth-files/fields`).
- Extend `ClaudeSidecarClient` with a `patch_auth_file_disabled` helper.
- Include each Claude account's `disabled` state (exposed as `paused`) in the routing response and in `SidecarAuthAccount` rows (quota endpoint, accounts list, dashboard card).
- Add a Pause/Resume toggle next to the priority input in the Settings routing section, on each sidecar account row in the Accounts tab detail view, and on each account row in the dashboard CLIProxyAPI card.
- Keep CLIProxyAPI auth files as the only source of truth; codex-lb stores no pause state.

## Impact

- Affected specs: `dashboard-sidecar-management`
- Affected backend code: `app/core/clients/claude_sidecar.py`, `app/modules/claude_sidecar/schemas.py`, `app/modules/claude_sidecar/service.py`, `app/modules/claude_sidecar/api.py`, `app/modules/accounts/schemas.py`, `app/modules/accounts/sidecar_summary.py`
- Affected frontend code: `frontend/src/features/settings/schemas.ts`, `frontend/src/features/settings/api.ts`, `frontend/src/features/settings/hooks/use-settings.ts`, `frontend/src/features/settings/components/sidecar-integration-card.tsx`, `frontend/src/features/settings/components/claude-sidecar-settings.tsx`, `frontend/src/features/accounts/schemas.ts`, `frontend/src/features/accounts/components/synthetic-account-detail.tsx`, `frontend/src/features/dashboard/components/account-card.tsx`
- No migrations or service restarts required.
