## Why

Operators can already enforce a reasoning effort on native Codex traffic per codex-lb API key (`enforced_reasoning_effort`), but there is no way to set a reasoning effort for the sidecar providers (CLIProxyAPI/Claude, OpenRouter, OmniRoute, Ollama). Today the only way a sidecar request gets an effort is when the client sends one explicitly or when a model-name suffix (e.g. `-high`) is parsed, and operators do not trust the effort clients (e.g. Cursor) send. Operators want a single per-provider override effort that is forced onto every sidecar request regardless of what the client sends, configurable from both the Settings page and the Accounts/Dashboard cards.

## What Changes

- Persist one nullable reasoning effort override per sidecar provider in `dashboard_settings` (field names retained for compatibility):
  - `claude_sidecar_default_reasoning_effort`
  - `openrouter_sidecar_default_reasoning_effort`
  - `omniroute_sidecar_default_reasoning_effort`
  - `ollama_sidecar_default_reasoning_effort`
- Allow values `none|minimal|low|medium|high|xhigh`, plus unset/null meaning "do not inject anything". `xhigh` is labeled `Extra high` in the UI.
- Force the configured override onto sidecar chat payloads, overriding any client `reasoning_effort` / nested `reasoning.effort` (the nested effort is stripped). A Claude model-name suffix effort is the highest precedence and beats the override. For Ollama the override maps to the `think` field and is applied even when the request already enabled thinking.
- Expose the override effort as a dropdown in each provider's Settings integration card and mirror it on the corresponding synthetic account card in the Accounts detail view and the Dashboard Accounts section. Both controls read and write the same `/api/settings` field.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `chat-completions-compat`: Sidecar chat payloads gain a per-provider reasoning effort override that is forced over any client-supplied effort (a Claude model-name suffix still wins).
- `frontend-architecture`: Settings and Accounts/Dashboard sidecar cards expose the same provider default effort and both persist through the settings update endpoint.

## Impact

- Backend: `app/db/models.py`, a new Alembic revision, `app/modules/settings/{schemas,service,repository,api}.py`, the four `app/core/clients/*_sidecar.py` configs, and the four sidecar dispatch builders plus `sidecar_model_profiles.py`.
- Frontend: `frontend/src/features/settings/{schemas.ts,payload.ts}`, the shared `sidecar-integration-card.tsx`, the four provider settings wrappers, and the Accounts/Dashboard synthetic card components.
- Reuses the existing `PUT /api/settings` persistence and settings cache; no new public API endpoints, no new dependencies, no service restart required.
