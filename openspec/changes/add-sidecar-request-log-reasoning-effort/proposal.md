## Why

Sidecar chat-completions requests (CLIProxyAPI/Claude, OpenRouter, OmniRoute, Ollama) currently persist no reasoning effort at all in `request_logs`, so the dashboard shows nothing in the model cell for sidecar rows. Operators also cannot see what a client (e.g. Cursor) originally asked for versus the per-provider override that codex-lb forced onto the forwarded request. This change records both values for sidecar traffic and surfaces them in the dashboard, mirroring the existing requested-vs-actual service-tier treatment.

This change is scoped to sidecars only. Native Codex request logs are out of scope.

## What Changes

- Add a nullable `requested_reasoning_effort` column to `request_logs`, keeping the existing `reasoning_effort` as the effective/forwarded value.
- For each sidecar dispatch builder, capture the client-sent effort (top-level `reasoning_effort` or nested `reasoning.effort`) before any per-provider override / Claude model-name-suffix effort / Ollama `think` mapping is applied, and the effort actually forwarded after, then persist both on the sidecar request log.
- Backfill is not required; `requested_reasoning_effort` stays `NULL` for pre-migration rows.
- Expose `requestedReasoningEffort` in the `GET /api/request-logs` response and render it in the dashboard recent-requests table (and detail drawer) only when it differs from the effective effort.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `chat-completions-compat`: Sidecar chat-completions request logs persist the client-requested reasoning effort separately from the effective effort forwarded to the provider.
- `frontend-architecture`: The dashboard request-log API exposes the requested reasoning effort and the recent-requests UI shows it when it differs from the effective effort.

## Impact

- Schema: new nullable `request_logs.requested_reasoning_effort` column plus a single-head Alembic revision (`upgrade`/`downgrade`); no backfill.
- Backend: `app/db/models.py`, the new migration, a shared effort-reader in `app/modules/proxy/sidecar_model_profiles.py`, the four dispatch builders/log writers in `app/modules/proxy/{claude_sidecar_dispatch.py,openrouter_sidecar_dispatch.py,omniroute_sidecar_dispatch.py,ollama_sidecar_dispatch.py}`, and the `requested_reasoning_effort` pass-through in `app/modules/request_logs/{repository,schemas,mappers}.py`.
- Frontend: `frontend/src/features/dashboard` request-logs table and its row schema/mapping.
- No new public API endpoints, no new dependencies. Native Codex request-log paths are NOT touched.
