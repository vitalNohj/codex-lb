## Why

Dashboard model aliases (`{alias -> real_model}`) already resolve on chat
requests, but they were invisible to `GET /v1/models`. Discovery-only clients
(for example Hermes) only allow models the catalog advertises, so they were
forced to select provider-prefixed target ids (e.g. `cohere/...`, `or/cohere/...`)
that the client can mis-route locally. Operators want a neutral alias id (e.g.
`north-mini-code`) to be a first-class discoverable model.

Separately, some aliases point at models whose real advertised context window
differs from the operator's intent (e.g. a DeepSeek "1M mode" alias). Operators
want to advertise a chosen `context_length` on the alias catalog row only,
without touching routing, upstream limits, or the sidecar wire model.

## What Changes

- Advertise each configured model alias as its own entry on `GET /v1/models`,
  cloning the target model's catalog metadata when the target is visible, or
  falling back to the sidecar default fields when the target is unknown.
- Hide an alias entry when its resolved target is not visible for the requesting
  API key. Never override an existing catalog id (case-insensitive).
- Gate alias access on the alias id itself before resolution, so a restricted
  API key can allow an alias id directly and cannot reach a disallowed target
  through an alias.
- Add an optional per-alias catalog overlay (`custom_alias_catalog`) that patches
  the advertised `context_length` (and mirrored `contextLength`,
  `capabilities.context_length`, `metadata.context_window`,
  `metadata.input_context_window`) on the alias catalog row only.
- Persist the overlay on `DashboardSettings.custom_alias_catalog_json`, reconcile
  it against the configured alias map on save (drop orphan keys and rows without
  a positive integer context length), and expose it through the settings API and
  dashboard Routing UI (Advanced context-length presets per alias row).

## Impact

- Affected specs: `model-catalog-compat`, `chat-completions-compat`.
- Affected code: `app/modules/proxy/model_aliasing.py`,
  `app/modules/proxy/custom_alias_catalog.py`, `app/modules/proxy/api.py`,
  `app/modules/settings/{api,service,schemas,repository}.py`, `app/db/models.py`,
  `app/db/alembic/versions/20260706_000000_add_custom_alias_catalog.py`,
  `frontend/src/features/settings/**`.
- Database: adds `dashboard_settings.custom_alias_catalog_json` (`Text`, default
  `"{}"`).
- Catalog overlays affect `GET /v1/models` only; routing, upstream limits, and
  sidecar wire models are unchanged.
