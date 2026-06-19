## 1. Shared sidecar card autosave

- [x] 1.1 Replace `saveConfig`/`clearApiKey`/`clearManagementKey` in `sidecar-integration-card.tsx` with action-based persistence helpers (`persistConfig`, `addApiKey`, `addManagementKey`) that reuse `buildPatch` + `buildSettingsUpdateRequest` and run the connection test after a successful config persist.
- [x] 1.2 Persist prefix add/remove, prefix strip toggle, and full-model add/remove immediately.
- [x] 1.3 Persist base URL and timeout/cache fields on blur or Enter; keep invalid values from persisting.
- [x] 1.4 Update `Secrets` to render `Add API key` (and `Add management key` for CLIProxyAPI) and remove the `Actions` (Save/Clear) UI.

## 2. Provider wrappers

- [x] 2.1 Remove `SidecarIntegrationCard.Actions` usage from `claude-sidecar-settings.tsx`, `openrouter-sidecar-settings.tsx`, and `omniroute-sidecar-settings.tsx`.

## 3. Tests

- [x] 3.1 Update `sidecar-integrations.test.tsx` for immediate strip-toggle/discovered-model persistence, conflict blocking, and backend conflict surfacing.
- [x] 3.2 Update `claude-sidecar-settings.test.tsx`, `openrouter-sidecar-settings.test.tsx`, `omniroute-sidecar-settings.test.tsx` for no Save/Clear buttons, Add key actions, autosave timing, and auto-test after config persist.
- [x] 3.3 Update `discovered-models-browser.test.tsx` empty-state copy if it references the removed Save/test flow.

## 4. Validation

- [x] 4.1 Run focused `npx vitest run` for the touched settings test files from `frontend/`.
- [x] 4.2 Run `openspec validate autosave-sidecar-integrations --strict` and `openspec validate --specs`.
- [x] 4.3 Check lints on edited files.
