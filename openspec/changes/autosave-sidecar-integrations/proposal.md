## Why

The shared sidecar integration settings card (CLIProxyAPI, OpenRouter, OmniRoute) forces operators to edit fields and then click a separate `Save` button before anything persists, and exposes `Clear API key` / `Clear management key` buttons to manage stored secrets. This is unnecessary friction: every meaningful edit (enable toggle, prefix, full model) can persist the moment the operator performs the action, and secrets can be replaced with an explicit `Add key` action that overwrites the stored value. Removing `Save`, `Clear API key`, and `Clear management key` simplifies the integration cards.

## What Changes

- Remove the generic `Save` button from all three sidecar integration sections.
- Remove the `Clear API key` and `Clear management key` buttons from the sidecar integration sections.
- Add an explicit `Add API key` action next to the API key input (and `Add management key` for CLIProxyAPI). Adding a key persists the new value, overwriting any previously stored key, then clears the input.
- Persist edits as the operator makes them: enable toggle, add/remove prefix, prefix strip checkbox, and add/remove full model (including discovered-model selections) all save immediately. Base URL and timeout/cache fields save on blur or Enter.
- Keep existing validation and conflict behavior: invalid base URL/timeout values are not persisted, cross-integration prefix/full-model conflicts block persistence, and backend conflict errors surface inline.
- Keep the automatic connection test after a successful configuration save; the enable toggle still does not trigger an auto-test.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `frontend-architecture`: The Settings page sidecar integration save contract changes from manual `Save`/`Clear` to action-based autosave with explicit `Add key` controls.

## Impact

- Affects the shared sidecar card (`sidecar-integration-card.tsx`) and the three provider wrappers (`claude-sidecar-settings.tsx`, `openrouter-sidecar-settings.tsx`, `omniroute-sidecar-settings.tsx`).
- Reuses the existing `PUT /api/settings` persistence path and the existing `/api/{claude,openrouter,omniroute}-sidecar/test` endpoints.
- Adds no new dependencies, database schema changes, or public API contracts.
