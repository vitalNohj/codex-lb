# Tasks

## 1. Backend

- [x] 1.1 Add `patch_auth_file_disabled` to `ClaudeSidecarClient`.
- [x] 1.2 Add `paused` to `ClaudeSidecarRoutingAccount` and `SidecarAuthAccount`; add `ClaudeSidecarAccountPausedUpdate` schema.
- [x] 1.3 Add `set_account_paused` service method and `PUT /api/claude-sidecar/routing/paused` route.
- [x] 1.4 Thread `disabled` into sidecar auth rows (`service.py` `_to_auth_account`, `sidecar_summary.py` `_auth_row`).
- [x] 1.5 Backend tests: client patch, service/API pause update, paused state in routing + quota responses.

## 2. Frontend

- [x] 2.1 Add `paused` to routing account + sidecar auth Zod schemas; add `setClaudeSidecarAccountPaused` API fn.
- [x] 2.2 Add `pausedMutation` to `useClaudeSidecar`.
- [x] 2.3 Pause/Resume toggle in Settings routing section rows.
- [x] 2.4 Pause/Resume toggle on sidecar auth rows in Accounts tab (`synthetic-account-detail.tsx`).
- [x] 2.5 Pause/Resume toggle on dashboard CLIProxyAPI card rows (`account-card.tsx`).
- [x] 2.6 Frontend tests for toggle rendering + mutation.

## 3. Validation

- [x] 3.1 `openspec validate add-cliproxy-account-pause --strict`.
- [x] 3.2 Targeted backend pytest + frontend vitest + lints.
