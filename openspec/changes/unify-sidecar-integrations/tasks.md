## 1. Config dataclasses (normalized shape)

- [x] 1.1 Add a `SidecarPrefix` type (`prefix: str`, `strip: bool`) and update `ClaudeSidecarConfig` (`app/core/clients/claude_sidecar.py`) to use `prefixes: tuple[SidecarPrefix, ...]` plus a `full_models: tuple[str, ...]`.
- [x] 1.2 Update `OpenRouterSidecarConfig` (`app/core/clients/openrouter_sidecar.py`) with the same `prefixes` (`{prefix, strip}`) and new `full_models` fields.
- [x] 1.3 Update `OmniRouteSidecarConfig` (`app/core/clients/omniroute_sidecar.py`) to add `prefixes` (`{prefix, strip}`) and rename/alias `selected_models` to `full_models`.

## 2. Unified routing resolver (backend)

- [x] 2.1 Create `app/modules/proxy/sidecar_routing.py` with a pure resolver: input = effective model + enabled integration configs, output = `(provider, wire_model)` or `None`. Implement full-name pass (case-insensitive exact, wire model as-is) then longest-prefix pass (strip iff row flag), with deterministic Claude→OpenRouter→OmniRoute tiebreak.
- [x] 2.2 Add prefix-variant handling (`-`/`_` interchange) and longest-match selection in the resolver; cover empty prefix/full-model lists.
- [x] 2.3 Remove the built-in alias list `_BUILTIN_SIDECAR_ALIAS_PREFIXES` from `app/modules/proxy/sidecar_prefix.py`; retire `matching_sidecar_prefix`/`strip_sidecar_model_prefix` usage in favor of the resolver (deleted the module; catalog alias IDs now derive from strip-enabled prefixes).
- [x] 2.4 Replace the per-integration matchers (`is_*_sidecar_model`, `*_wire_model`) call sites with the resolver; keep each provider's `proxy_chat_to_*` dispatch and payload-builders, passing the resolver's `wire_model` (new `wire_model` kwarg).
- [x] 2.5 Rewire `v1_chat_completions` (`app/modules/proxy/api.py`) to call the resolver once and dispatch to the owning provider; preserve reservation/log use of the effective (un-stripped) model.
- [x] 2.6 Rewire the Responses sidecar dispatch (`app/modules/proxy/api.py`) to use the resolver with the same precedence/strip rules.

## 3. Persistence schema + migration

- [ ] 3.1 Update `DashboardSettings` (`app/db/models.py:593-743`): change `*_model_prefixes_json` semantics to `{prefix, strip}` arrays; add `claude_sidecar_full_models_json` and `openrouter_sidecar_full_models_json`; treat `omniroute_sidecar_selected_models_json` as OmniRoute's full-models store (keep column name to minimize churn).
- [ ] 3.2 Add an Alembic revision on the current single head (`alembic heads` to confirm parent) implementing upgrade: prefix strings → `{prefix, strip}` (strip = ends-with `-`/`_`), seed CLIProxyAPI `cp-`/`cp_` (strip true) where absent, ensure full-model columns default `[]`, preserve OmniRoute selected models as full models.
- [ ] 3.3 Implement the downgrade: collapse `{prefix, strip}` back to string arrays, drop added full-model columns, restore prior OmniRoute naming/semantics.
- [ ] 3.4 Add migration tests (upgrade backfill parity + downgrade) and detect/log (do not drop) any pre-existing cross-integration prefix collisions.

## 4. Settings schemas + uniqueness validation

- [ ] 4.1 Update Pydantic settings models (`app/modules/settings/schemas.py:162-269`): response + update models expose `{prefix, strip}` prefixes and `full_models` for all three integrations; keep management-key fields CLIProxyAPI-only.
- [ ] 4.2 Update normalization validators (base URL, prefix normalization to lowercase, full-model trimming) for the new shapes.
- [ ] 4.3 Add a cross-integration uniqueness validator over the post-update state: a prefix or full-model value may own at most one integration; allow prefix-vs-full-model textual coincidence across integrations. Reject with a structured conflict error (`code`, `value`, `kind`, `owning_integration`).
- [ ] 4.4 Wire the conflict error into the settings update API response envelope so the frontend can render it.
- [ ] 4.5 Update `*_config_from_settings` builders in the dispatch modules to construct the new config shapes from settings.

## 5. Model catalog advertising

- [ ] 5.1 Update sidecar model-catalog advertising (`app/modules/proxy/api.py` ~1894 and any per-integration summary) to advertise each enabled integration's `full_models` uniformly, dedup by resolver-owner, and not advertise prefixes.

## 6. Shared frontend component

- [ ] 6.1 Create `SidecarIntegrationCard` compound component (provider + subcomponents: Header, EnableToggle, Callout, BaseUrl, ApiKey, ManagementKey, Prefixes, FullModels, DiscoveredModels, Timeouts, Actions) under `frontend/src/features/settings/components/`, using `use()` context per the composition skill.
- [ ] 6.2 Build a shared `DiscoveredModelsBrowser` (collapsible, searchable) replacing `openrouter-model-browser.tsx` and `omniroute-model-browser.tsx`.
- [ ] 6.3 Implement the Prefixes editor with a per-entry "remove prefix before forwarding" checkbox and inline red-text rejection naming the conflicting integration; implement the FullModels editor rendered outside the browser (add via discovered-model click or typed full name).
- [ ] 6.4 Add client-side cross-integration uniqueness checks (prefix/full-model) with the prefix-vs-full-model coincidence exception; block Save while unresolved; surface backend conflict errors.
- [ ] 6.5 Replace `{claude,openrouter,omniroute}-sidecar-settings.tsx` with provider-specific compositions of the shared card (CLIProxyAPI includes ManagementKey + poll interval; others omit ManagementKey); update `settings-page.tsx` wiring.
- [ ] 6.6 Update frontend schemas/payload (`schemas.ts`, `payload.ts`) and `use-settings` hooks for the new `{prefix, strip}` + full-models shapes; add subtitle copy stating full model names take precedence over prefixes across all integrations.

## 7. Tests

- [ ] 7.1 Backend resolver unit tests: full-name beats prefix, longest-prefix wins, per-prefix strip on/off, full-name never stripped, disabled integrations ignored, no-match fallthrough.
- [ ] 7.2 Chat-completions routing tests asserting reservation/log use the effective model and wire model reflects strip rules.
- [ ] 7.3 Responses-path routing test mirroring precedence/strip behavior.
- [ ] 7.4 Settings uniqueness validator tests: duplicate prefix rejected, duplicate full-model rejected, prefix-vs-full-model coincidence accepted, structured error shape.
- [ ] 7.5 Frontend tests (vitest): per-prefix strip toggle, inline duplicate rejection text, discovered-model click adds to full-models, Save blocked on conflict.

## 8. Validation + docs

- [ ] 8.1 Run `openspec validate unify-sidecar-integrations --strict` and `openspec validate --specs`.
- [ ] 8.2 Run `uv run pytest` for touched backend modules and `npx vitest run` for touched frontend files; run `uv run ruff`.
- [ ] 8.3 Update `openspec/specs/<capability>/context.md` (or change-level context) with the unified routing rationale, the `minimax/` vs `minimax/minimax-m3` precedence example, and the strip-flag migration note.
