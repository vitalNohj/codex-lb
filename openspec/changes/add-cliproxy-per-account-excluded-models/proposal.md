# Add CLIProxyAPI Per-Account Model Exclusion List

## Why

A Claude account can be entitled to a different set of models than its siblings: one subscription tier
carries a model the other does not. When CLIProxyAPI offers a request to an account that cannot serve
the requested model, that request fails instead of landing on an account that can serve it.

CLIProxyAPI already solves this with the per-auth-file `excluded_models` field: it skips credentials
whose patterns match the wire model and weighted-round-robins among the rest. Today codex-lb exposes
`disabled` (Pause) but not `excluded_models`, so the only way to hide one model on one account is to
hand-edit an auth JSON. Operators need to add and remove exclusions from the dashboard, and to reverse
a change later with a click rather than a code edit.

## What Changes

- Add a dashboard endpoint `PUT /api/claude-sidecar/routing/excluded-models` taking `{ name, excludedModels }`
  and patching that auth file's `excluded_models` field through CLIProxyAPI's Management API
  (`PATCH /v0/management/auth-files/fields`). The request replaces the whole list; `[]` clears it.
- Extend `ClaudeSidecarClient` with a `patch_auth_file_excluded_models` helper.
- Add `app/modules/claude_sidecar/excluded_models.py` with normalization plus a token-free read of the
  `excluded_models` key from an auth file on disk, because CLIProxyAPI 7.2.135 omits the field from
  `GET /v0/management/auth-files`.
- Include each Claude account's `excludedModels` list in the routing response, the quota snapshot, and
  `SidecarAuthAccount` rows (quota endpoint, accounts list, dashboard card).
- Add an excluded-models editor (family switches plus custom pattern chips, autosaving) to the Settings
  CLIProxyAPI routing rows and the Accounts Claude detail view, plus compact excluded badges on the
  dashboard Claude card and list row.
- Keep CLIProxyAPI auth files as the only source of truth; codex-lb stores no desired copy of its own.

## Impact

- Affected specs: `dashboard-sidecar-management`, `frontend-architecture`
- Affected backend code: `app/core/clients/claude_sidecar.py`, `app/modules/claude_sidecar/excluded_models.py`,
  `app/modules/claude_sidecar/schemas.py`, `app/modules/claude_sidecar/service.py`,
  `app/modules/claude_sidecar/api.py`, `app/modules/claude_sidecar/quota.py`,
  `app/modules/accounts/schemas.py`, `app/modules/accounts/sidecar_summary.py`
- Affected frontend code: `frontend/src/features/settings/schemas.ts`, `frontend/src/features/settings/api.ts`,
  `frontend/src/features/settings/hooks/use-settings.ts`,
  `frontend/src/features/settings/lib/excluded-model-families.ts`,
  `frontend/src/features/settings/components/excluded-models-editor.tsx`,
  `frontend/src/features/settings/components/sidecar-integration-card.tsx`,
  `frontend/src/features/settings/components/claude-sidecar-settings.tsx`,
  `frontend/src/features/accounts/schemas.ts`,
  `frontend/src/features/accounts/components/synthetic-account-detail.tsx`,
  `frontend/src/features/dashboard/components/account-card.tsx`,
  `frontend/src/features/dashboard/components/account-list.tsx`
- No migrations and no service restarts required. Existing quota snapshots without the key read as an
  empty list.
