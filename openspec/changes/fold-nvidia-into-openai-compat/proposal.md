## Why

The NVIDIA External Integration is a verbatim clone of the generic OpenAI-compatible endpoint: same wire protocol (`GET /models` + `POST /chat/completions` with a bearer key), same routing inputs, same pricing path, same dashboard card. It predates the `+` endpoint list and only differs by a pre-filled base URL and a dedicated routing tie-break slot. Keeping it means every fix to the OpenAI-compat dispatcher has to be mirrored by hand into a second 770-line module.

## What Changes

- Remove the NVIDIA sidecar module, dispatch, client, settings columns, dashboard APIs, synthetic account branch, and Settings tab.
- Migrate any configured NVIDIA settings (base URL, encrypted API key, prefixes, full models, timeouts, cache TTL, effort override, enabled flag) into one `openai_compat_endpoints_json` entry named `NVIDIA` so the operator loses nothing.
- Drop the `dashboard_settings.nvidia_sidecar_*` columns.
- Remove `nvidia` from `SIDECAR_PROVIDER_ORDER`, the dashboard account-type filter, the external-pricing provider map, and the `nvidia_sidecar` request-log source.

## Non-goals

- Do not change the OpenAI-compat endpoint contract.
- Do not backfill historical `nvidia_sidecar` request-log rows (none exist on the reference deployment; the migration rewrites the `source` column if any do).
- Do not edit `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, or hand-write `docs/`.
- Do not restart `codex-lb.service` unprompted.

## Capabilities

### Removed Capabilities

- `nvidia-sidecar-management` (never synced to `openspec/specs`; delivered by `add-nvidia-sidecar-routing`).

### Modified Capabilities

- `database-migrations`: fold-and-drop migration for the NVIDIA columns.

## Impact

- Backend: 23 files touch `nvidia`; one module, one dispatch, one client, one summary builder, one API router deleted; branches removed from proxy, dashboard, accounts, settings, pricing.
- Frontend: `nvidia-sidecar-settings.tsx` deleted; provider branches removed from account card/list/detail/actions/filter, settings schema/payload/api/hooks, prefs store.
- Operator: the NVIDIA tab becomes an `NVIDIA` entry in the same card, one row down, with the same URL and key.
