## Why

Merging upstream request-speed columns into the fork's compact request-log table compressed the existing column widths and made rows difficult to scan. Operators need the fork's compact layout restored without removing upstream's richer request-log metrics.

## What Changes

- Add a `Simplified`/`Expanded` view control to the dashboard Request Logs filter area.
- Make `Simplified` the default and persist the operator's selection locally.
- Restore the fork's eight-column simplified layout: Time, Account with inline Plan, API Key, Model, Tokens, Cost, Status, and Details.
- Preserve the full upstream column set in expanded mode: Time, Account, Plan, API Key, Model, Transport, Status, TTFT, TPS, Tokens, Cost, and Details.
- Keep complete request metadata available in the Request Details dialog in both modes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frontend-architecture`: Dashboard request logs gain locally persisted simplified and expanded table presentations.

## Impact

- Dashboard request-log filters and table components in `frontend/src/features/dashboard/components/`
- Dashboard local preferences in `frontend/src/hooks/use-dashboard-preferences.ts`
- Focused frontend component and preference tests
- No backend API, database, migration, dependency, or deployment configuration changes
