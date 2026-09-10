# Tasks

## 1. Backend

- [x] 1.1 Add `app/modules/claude_sidecar/excluded_models.py` with `normalize_excluded_models`,
      `excluded_models_from_mapping`, and `excluded_models_from_auth_file`.
- [x] 1.2 Add `patch_auth_file_excluded_models` to `ClaudeSidecarClient`.
- [x] 1.3 Add `excluded_models` to `ClaudeSidecarRoutingAccount` and `SidecarAuthAccount`; add
      `ClaudeSidecarAccountExcludedModelsUpdate` schema.
- [x] 1.4 Add `set_account_excluded_models` service method plus
      `PUT /api/claude-sidecar/routing/excluded-models` route, and patch the quota snapshot on success.
- [x] 1.5 Thread `excluded_models` into routing accounts, the quota snapshot round-trip, and sidecar auth
      rows (`service.py` `_to_auth_account`, `sidecar_summary.py` `_auth_row`).
- [x] 1.6 Backend tests: normalize/disk-read unit tests, PUT integration tests, exclusion list present in
      routing and quota responses with no token fields.

## 2. Frontend

- [x] 2.1 Add `excludedModels` to routing account + sidecar auth Zod schemas; add
      `setClaudeSidecarAccountExcludedModels` API fn.
- [x] 2.2 Add `frontend/src/features/settings/lib/excluded-model-families.ts` family-to-pattern map.
- [x] 2.3 Add the `ExcludedModelsEditor` component (family switches, custom chips, add-pattern input).
- [x] 2.4 Add the `excludedModelsMutation` to `useClaudeSidecar`.
- [x] 2.5 Render the editor in the Settings routing rows and on the Accounts Claude detail view.
- [x] 2.6 Render compact excluded badges on the dashboard Claude card and list row.
- [x] 2.7 Frontend tests: editor behavior, settings PUT payloads, card badge rendering, MSW handler coverage.

## 3. Validation

- [x] 3.1 `openspec validate add-cliproxy-per-account-excluded-models --strict`.
- [x] 3.2 Targeted backend pytest + frontend vitest + `bun run build`.
- [x] 3.3 Grep gate: no account email and no model-family special case in `app/`.
- [x] 3.4 Opt-in native contracts against pinned CLIProxyAPI commit
      `856ddd8df746a38a6033dbbf6c140974bf5aea0f`, under a deny-all-network sandbox with synthetic
      accounts, proving exact vs explicit wildcard behavior, retry, exhaustion, alias ordering,
      runtime toggling, and actual saved-file delivery through the watcher and update consumer.
- [x] 3.5 Validate the Python-to-Go save, read-back and clear boundary with the real-handler
      contract bodies in `tests/contract/cliproxy_exclusions/http`, using CLIProxyAPI's real
      management handler, Manager and FileTokenStore with synthetic accounts. The adapted public
      launcher is unexecuted, and the preserved full-main fixture in
      `tests/integration/test_claude_sidecar_excluded_models_contract.py` remains unexecuted.
