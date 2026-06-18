## 1. OpenSpec

- [ ] 1.1 Add frontend-architecture delta requirement and scenarios
- [ ] 1.2 Run `openspec validate add-dashboard-account-pause --strict`

## 2. UI

- [ ] 2.1 Add `pause` action type and `Pause` button to normal dashboard account card
- [ ] 2.2 Keep synthetic sidecar cards without pause/resume controls
- [ ] 2.3 Wire the dashboard page `pause` action to the existing `pauseMutation`

## 3. Tests

- [ ] 3.1 Pause button visible and dispatches `pause` action on a normal active account
- [ ] 3.2 Paused account shows `Resume` and hides `Pause`
- [ ] 3.3 Synthetic sidecar cards do not show `Pause`

## 4. Verify

- [ ] 4.1 `openspec validate add-dashboard-account-pause --strict`
- [ ] 4.2 Focused Vitest for dashboard account card(s)
- [ ] 4.3 Frontend typecheck and lints
