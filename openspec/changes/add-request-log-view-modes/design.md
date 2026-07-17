## Context

The fork previously rendered request logs as an eight-column table using percentage widths across a 960px minimum width. It kept plan tier inline with account identity and left transport details to the request-details dialog. Upstream later added standalone Plan, Transport, TTFT, and TPS columns. The merge preserved the old minimum width while combining both column sets, so twelve columns now compete for space intended for eight.

The dashboard already has a local Zustand preference store for display-only choices such as account card/list mode. Request filters already provide a compact top row containing search and timeframe controls.

## Goals / Non-Goals

**Goals:**

- Restore the fork's exact eight-column request-log layout as `Simplified`.
- Keep upstream's complete twelve-column table as `Expanded`.
- Default to Simplified and remember the operator's last selection in the browser.
- Avoid duplicating request-row data derivation, dialog behavior, or API calls.
- Keep both modes usable on narrower screens through horizontal overflow.

**Non-Goals:**

- Do not change request-log API fields, filtering, pagination, persistence, or collection.
- Do not hide data from the Request Details dialog.
- Do not add a server-side setting, database field, migration, or dependency.
- Do not redesign unrelated dashboard tables.

## Decisions

### Use one table renderer with mode-dependent cells

`RecentRequestsTable` will receive a typed view mode and conditionally include the mode-specific headers and cells. Shared columns and row derivations remain in one component. Simplified mode will render Plan inside Account and omit standalone Plan, Transport, TTFT, and TPS cells. Expanded mode will render every upstream column.

Alternative considered: two separate table components. Rejected because request labels, privacy behavior, error presentation, details actions, and new upstream fields would need duplicate maintenance.

Alternative considered: hide expanded cells with CSS. Rejected because hidden table cells would make mode-specific widths, accessibility, and tests harder to reason about.

### Keep preference in existing dashboard preference store

Add `DashboardRequestLogViewMode = "simplified" | "expanded"` plus a persisted `requestLogViewMode` field and setter to `useDashboardPreferencesStore`. Missing or invalid stored values resolve to `simplified`.

Alternative considered: backend dashboard settings. Rejected because this is a browser-local presentation choice and does not justify an API/schema/migration change.

### Put text toggle in request filter top row

`RequestFilters` will render a compact, labeled two-option radio group after the timeframe control. Text labels remain visible because `Simplified` and `Expanded` are clearer than icons. On narrow layouts the top row may wrap while search keeps available width.

### Preserve mode-specific width strategies

Simplified mode will use the prior 960px minimum and percentage widths:

- Time 10%
- Account 18%
- API Key 14%
- Model 16%
- Tokens 10%
- Cost 8%
- Status 10%
- Details 14%

Expanded mode will use explicit widths and a larger minimum width so added Plan, Transport, TTFT, and TPS columns do not compress flexible identity columns. Horizontal scrolling is acceptable when viewport width cannot fit the complete dataset.

### Keep details dialog complete and mode-independent

Both modes open the same Request Details dialog. Transport, source, elapsed time, TTFT, queue latency, TPS, requested/effective effort, cost, and errors remain available regardless of visible table columns.

## Risks / Trade-offs

- [Expanded mode requires horizontal scrolling on smaller screens] → Use an intentional expanded minimum width instead of compressing text until columns become unreadable.
- [Conditional cells can drift from headers] → Add tests that assert exact header order and row cell count/content in both modes.
- [Local storage contains stale or malformed values] → Accept only `simplified` or `expanded`; otherwise restore and persist `simplified`.
- [Existing preference-store initialization grows] → Extend the established store instead of introducing a second persistence mechanism.

## Migration Plan

1. Ship frontend and OpenSpec changes together.
2. Existing browser profiles have no request-log mode key, so they initialize to Simplified.
3. Rollback removes the view control and ignores the unused local-storage key; no data migration is required.

## Open Questions

None.
