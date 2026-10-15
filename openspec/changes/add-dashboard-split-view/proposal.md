## Why

On 2K and 4K screens the dashboard is capped at 1500px and stacks every section vertically, leaving most of the screen empty while operators scroll between accounts and request logs.

## What Changes

- Add a `Split view` toggle in the dashboard header beside the overview timeframe selector and refresh button.
- When enabled, the dashboard (and the app header and status bar, so edges stay aligned) spans the full viewport width.
- At ≥1792px (`3xl`) the accounts panel and request logs render side by side; at ≥2880px (`4xl`) the KPI tiles and usage donuts share one row.
- KPI tiles and account cards use fluid auto-fill columns in split view so density follows available width.
- The accounts panel defaults to roughly viewport height in split view; an operator-dragged height still wins.
- The toggle is off by default and persists locally in the browser.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frontend-architecture`: Dashboard gains a locally persisted wide-screen split-view layout.

## Impact

- Dashboard page, stats grid, and account cards in `frontend/src/features/dashboard/components/`
- App shell width in `App.tsx`, `app-header.tsx`, `status-bar.tsx` via `use-page-width.ts`
- Dashboard local preferences in `frontend/src/hooks/use-dashboard-preferences.ts`
- New `3xl`/`4xl` Tailwind breakpoints in `frontend/src/index.css`; i18n strings for en/ko/zh-CN
- No backend API, database, migration, dependency, or deployment changes
