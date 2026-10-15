## 1. Preference

- [x] 1.1 Add `splitViewEnabled` state, guarded local-storage read, and persisting setter to `use-dashboard-preferences.ts` with tests.

## 2. Layout

- [x] 2.1 Add `3xl` (112rem) and `4xl` (180rem) breakpoints in `index.css`.
- [x] 2.2 Add `usePageMaxWidthClass` and apply it to the app body, header, and status bar.
- [x] 2.3 Add `SplitViewToggle` beside the timeframe selector and refresh button.
- [x] 2.4 Render the split-view dashboard grid with shared section elements reused from the stacked layout.
- [x] 2.5 Use fluid auto-fill columns for KPI tiles and account cards in split view; seed the accounts panel height from the viewport.

## 3. Validate

- [x] 3.1 Dashboard-page tests cover toggle presence, pressed state, and layout switch.
- [x] 3.2 Run frontend typecheck, lint, and focused Vitest suites.
- [x] 3.3 Manually verify at 1080p, 2K, and 4K.
