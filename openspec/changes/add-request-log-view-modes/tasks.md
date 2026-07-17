## 1. Persist request-log view preference

- [x] 1.1 Add request-log view-mode read, validation, default, persistence, state, and setter coverage to `use-dashboard-preferences.test.ts`.
- [x] 1.2 Run the focused preference test and confirm the new cases fail because request-log view mode is not implemented.
- [x] 1.3 Add `DashboardRequestLogViewMode`, default `simplified` state, guarded local-storage initialization, and setter persistence to `use-dashboard-preferences.ts`.
- [x] 1.4 Run the focused preference test and confirm all preference cases pass.

## 2. Add accessible request-log mode control

- [x] 2.1 Add focused `RequestFilters` tests for the Simplified/Expanded radio group and change callback.
- [x] 2.2 Run the focused filter test and confirm it fails because the control is absent.
- [x] 2.3 Add typed view-mode props and a compact text radio group beside the timeframe selector in `request-filters.tsx`.
- [x] 2.4 Run the focused filter test and confirm the control tests pass.

## 3. Render simplified and expanded table layouts

- [x] 3.1 Add request-table tests that assert exact header order, plan placement, mode-specific metrics, row cell counts, and complete details-dialog metadata in both modes.
- [x] 3.2 Run the focused request-table test and confirm the new mode cases fail against the merged twelve-column-only table.
- [x] 3.3 Add a typed `viewMode` prop to `RecentRequestsTable` and restore the exact eight-column fork layout for Simplified mode.
- [x] 3.4 Preserve the twelve-column upstream layout for Expanded mode with a minimum width large enough to prevent column compression.
- [x] 3.5 Keep shared row derivation, details action, dialog metadata, pagination, and sidecar labels unchanged across both modes.
- [x] 3.6 Run the focused request-table test and confirm all table cases pass.

## 4. Wire dashboard state

- [x] 4.1 Extend dashboard-page tests to verify the stored view mode reaches both RequestFilters and RecentRequestsTable and that changing it calls the preference setter.
- [x] 4.2 Run the focused dashboard-page test and confirm the new wiring case fails.
- [x] 4.3 Read `requestLogViewMode` and `setRequestLogViewMode` from the existing dashboard preference store in `dashboard-page.tsx`.
- [x] 4.4 Pass the mode and setter to RequestFilters and pass the mode to RecentRequestsTable without changing filter or pagination state.
- [x] 4.5 Run the focused dashboard-page test and confirm the wiring case passes.

## 5. Validate

- [x] 5.1 Run the focused preference, filter, dashboard-page, and request-table Vitest suites from `frontend/`.
- [x] 5.2 Run frontend typecheck/build and confirm no new TypeScript errors.
- [x] 5.3 Read linter diagnostics for all edited frontend files and fix only issues introduced by this change.
- [x] 5.4 Run `openspec validate add-request-log-view-modes --strict`.
- [x] 5.5 Manually verify Simplified and Expanded at the dashboard's production-width request-log card, including persistence after reload and horizontal scrolling at narrow widths.
