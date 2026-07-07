## 1. Advertise aliases on /v1/models

- [x] 1.1 Build discoverable alias entries by cloning target metadata when the target is visible, else the sidecar default fields, setting `id=alias` and `owned_by=codex-lb`.
- [x] 1.2 Skip aliases whose id already exists (case-insensitive) or whose target is not visible for the API key.
- [x] 1.3 Append alias entries in `_build_models_response` and re-validate as `ModelListItem`.

## 2. Gate alias access before resolution

- [x] 2.1 Validate model access on the requested alias id before resolving it, then re-validate on the resolved/effective target.

## 3. Per-alias catalog overlay

- [x] 3.1 Add `custom_alias_catalog` load/reconcile/apply in `custom_alias_catalog.py` patching `context_length`, `contextLength`, `capabilities.context_length`, and `metadata.context_window`/`input_context_window` on alias rows only.
- [x] 3.2 Persist on `dashboard_settings.custom_alias_catalog_json` (migration revising `20260628_000000_add_model_aliases`).
- [x] 3.3 Thread the field through settings API/service/schemas/repository, reconciling against the alias map on save.
- [x] 3.4 Add the dashboard Routing UI (Advanced context-length presets per alias row) and remove catalog rows when an alias is deleted.

## 4. Cover the behavior

- [x] 4.1 Unit tests for alias entry building and catalog reconcile/filter/apply.
- [x] 4.2 Integration tests: aliases listed on `/v1/models`, alias hidden when target not allowed, catalog context-length applied, alias discoverable and routes through the sidecar.
- [x] 4.3 Frontend tests for saving and clearing the per-alias context-length override.

## 5. Validate the change

- [ ] 5.1 Run `openspec validate add-discoverable-model-aliases --strict` and the targeted `/v1/models` + alias tests.
