## Why

The three sidecar integrations (CLIProxyAPI/`claude_sidecar`, OpenRouter, OmniRoute) were each built independently, producing three near-duplicate ~230-270 line Settings components, two near-identical model browsers, three ~450 line dispatch modules, and three divergent model-matching rules (longest-prefix, first-prefix, exact-only). The fields they expose overlap heavily (base URL, API key, discovered models, prefixes), but the inconsistencies make the Settings page confusing and the routing logic hard to reason about. Unifying the data model, the routing/filter engine, and the UI removes the divergence, gives every integration the same capabilities (prefix routing + exact full-model routing), and lets a model be routed to exactly one owner.

## What Changes

- **Unify the model-routing/filter engine** across all sidecars into a single provider-agnostic resolver used by both `/v1/chat/completions` and the Responses endpoints. Resolution order: (1) **full model name** exact match (case-insensitive) across all enabled integrations wins and the model is sent **as-is** (never stripped); (2) otherwise **prefix** match across all enabled integrations, stripping the matched prefix only when that prefix's strip flag is set. **BREAKING** (routing semantics): OmniRoute gains prefix routing; CLIProxyAPI and OpenRouter gain exact full-model routing.
- **Per-prefix strip flag.** Prefixes become `{prefix, strip}` objects. **BREAKING** (data shape): replaces today's auto rule (strip only prefixes ending in `-`/`_`). Migration backfills existing prefixes so current effective behavior is preserved (`-`/`_`-ending → `strip: true`, others → `strip: false`).
- **Global uniqueness of prefixes and full model names** across all integrations, enforced **both** client-side (red-text rejection on add) and server-side (save rejected with a structured conflict error naming the value and the owning integration). The only intentional cross-integration relationship is a prefix on one integration vs. a full model name on another that share text (e.g. prefix `minimax/` vs. full name `minimax/minimax-m3`); the full model name takes precedence and is routed/sent as-is.
- **Generalize "selected models" into a single per-integration full-model list.** OmniRoute's existing `selected_models` becomes the shared full-models list; CLIProxyAPI and OpenRouter gain the same list. Clicking a discovered model or typing a full name both add to this one list, rendered **outside** the discovered-models browser.
- **CLIProxyAPI `cp-`/`cp_` aliases become default editable prefix rows** (seeded with `strip: true`), removing the hardcoded built-in alias list. Behavior is preserved by the seeded defaults.
- **Management key stays CLIProxyAPI-only.** All other fields (base URL, API key, prefixes + per-prefix strip, full models, discovered models, timeouts, cache TTL) are uniform across the three integrations.
- **Shared UI:** replace the three bespoke Settings components and two model browsers with one `<SidecarIntegrationCard>` compound component (Header / EnableToggle / Callout / BaseUrl / ApiKey / ManagementKey? / Prefixes-with-per-row-strip-checkbox / FullModels / DiscoveredModelsBrowser / Timeouts / Actions), dependency-injected per provider. Subtitle copy states that full model names take precedence over prefixes across all integrations.

## Capabilities

### New Capabilities
- _None._ This change unifies and modifies existing sidecar behavior; no new capability folder is introduced.

### Modified Capabilities
- `chat-completions-compat`: unified sidecar routing precedence (full-name-exact wins over prefix, globally), per-prefix strip semantics, and cross-integration uniqueness of prefixes/full-model-names; OmniRoute prefix routing and CLIProxyAPI/OpenRouter full-model routing.
- `responses-api-compat`: the same unified resolver decides OmniRoute (and any sidecar) routing for Responses-shaped requests.
- `model-catalog-compat`: advertise routable models uniformly per provider (full models + prefixes) instead of per-integration-specific rules.
- `frontend-architecture`: shared `<SidecarIntegrationCard>` compound component replaces the three duplicated sidecar Settings components and two model browsers; client-side prefix/full-name uniqueness validation with inline conflict reporting.
- `database-migrations`: migrate `*_model_prefixes_json` to `{prefix, strip}` objects, add `*_full_models_json` to CLIProxyAPI and OpenRouter, generalize OmniRoute `selected_models_json`, seed CLIProxyAPI default prefix rows, with upgrade/downgrade and historical-row backfill on a single head.

## Impact

- **Backend routing**: `app/modules/proxy/api.py` (`v1_chat_completions` precedence block ~2122-2180, Responses dispatch ~491-519), `app/modules/proxy/sidecar_prefix.py` (built-in alias list removed), `openrouter_sidecar_dispatch.py` / `omniroute_sidecar_dispatch.py` matchers replaced by a new shared resolver (e.g. `app/modules/proxy/sidecar_routing.py`); per-provider dispatch functions retained for the actual proxying.
- **Config dataclasses**: `ClaudeSidecarConfig`, `OpenRouterSidecarConfig`, `OmniRouteSidecarConfig` gain a normalized prefix (`{prefix, strip}`) and full-models shape.
- **Schema/persistence**: `DashboardSettings` columns (`app/db/models.py:593-743`), Pydantic settings models (`app/modules/settings/schemas.py:162-269`) including a new cross-integration uniqueness validator and structured conflict error; one new Alembic revision with backfill.
- **Frontend**: `frontend/src/features/settings/components/{claude,openrouter,omniroute}-sidecar-settings.tsx` and `{openrouter,omniroute}-model-browser.tsx` consolidated into the shared compound component; settings page wiring (`settings-page.tsx`), schemas/payload, and `use-settings` hooks updated.
- **Tests**: routing precedence/uniqueness (backend), migration upgrade/downgrade + backfill, and frontend uniqueness-rejection + per-prefix-strip UI.
