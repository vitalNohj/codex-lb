## Why

Operators can already enforce a reasoning effort on native Codex traffic per codex-lb API key (`enforced_reasoning_effort`), but there is no way to set a default reasoning effort for the sidecar providers (CLIProxyAPI/Claude, OpenRouter, OmniRoute, Ollama). Today the only way a sidecar request gets an effort is when the client sends one explicitly or when a model-name suffix (e.g. `-high`) is parsed. Operators want a single per-provider default effort that is injected automatically when the client did not specify one, configurable from both the Settings page and the Accounts/Dashboard cards.

## What Changes

- Persist one nullable default reasoning effort per sidecar provider in `dashboard_settings`:
  - `claude_sidecar_default_reasoning_effort`
  - `openrouter_sidecar_default_reasoning_effort`
  - `omniroute_sidecar_default_reasoning_effort`
  - `ollama_sidecar_default_reasoning_effort`
- Allow values `none|minimal|low|medium|high|xhigh`, plus unset/null meaning "do not inject anything". `xhigh` is labeled `Extra high` in the UI.
- Inject the configured default into sidecar chat payloads only when the request has no explicit effort: explicit client `reasoning_effort` / nested `reasoning.effort` wins, then the model-name suffix effort (Claude), then the provider default. For Ollama the default maps to the `think` field only when the request would not otherwise enable thinking.
- Expose the default effort as a dropdown in each provider's Settings integration card and mirror it on the corresponding synthetic account card in the Accounts detail view and the Dashboard Accounts section. Both controls read and write the same `/api/settings` field.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `chat-completions-compat`: Sidecar chat payloads gain a per-provider default reasoning effort that is applied only when no explicit client effort is present.
- `frontend-architecture`: Settings and Accounts/Dashboard sidecar cards expose the same provider default effort and both persist through the settings update endpoint.

## Impact

- Backend: `app/db/models.py`, a new Alembic revision, `app/modules/settings/{schemas,service,repository,api}.py`, the four `app/core/clients/*_sidecar.py` configs, and the four sidecar dispatch builders plus `sidecar_model_profiles.py`.
- Frontend: `frontend/src/features/settings/{schemas.ts,payload.ts}`, the shared `sidecar-integration-card.tsx`, the four provider settings wrappers, and the Accounts/Dashboard synthetic card components.
- Reuses the existing `PUT /api/settings` persistence and settings cache; no new public API endpoints, no new dependencies, no service restart required.
