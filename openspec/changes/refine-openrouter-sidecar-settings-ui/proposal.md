# Refine OpenRouter Sidecar Settings UI

## Why

The initial OpenRouter sidecar settings section exposed base URL and timeouts as prominently as the API key, and truncated the model catalog to 12 badges. Operators primarily need to save an API key, configure routing prefixes, and discover/search available models.

## What Changes

- Restructure the dashboard OpenRouter sidecar settings section to match the Claude sidecar layout: status badge header, help callout, divided enable row.
- Promote API key and model prefixes as the primary fields; collapse base URL and timeouts into an Advanced block (defaults unchanged).
- Add a health strip (configured / model count / last check) and a curated popular-models list with one-click provider-prefix add.
- Add a client-side searchable model browser over `GET /api/openrouter-sidecar/models` with per-model "add prefix" actions.
- Gate the dashboard models query so it only fetches when the sidecar is enabled and an API key is configured.

UI-only change. No backend behavior, API, schema, or routing changes; no spec deltas.

## Impact

- Affected code: `frontend/src/features/settings/` (OpenRouter sidecar component, new model browser + popular models module, hook query guard), frontend MSW fixtures.
- Affected specs: none (existing `openrouter-sidecar-management` requirements unchanged).
