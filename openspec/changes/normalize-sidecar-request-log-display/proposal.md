## Why

Sidecar request-log rows currently add sidecar-specific decoration under the Model column and replace the actual protocol label with `Sidecar HTTP`. This makes the Request Logs table visually noisy, breaks the compact row styling, and diverges from regular GPT/OpenCodex HTTP rows.

## What Changes

- Render sidecar request-log Model cells the same way as non-sidecar rows: model label, warmup marker, and requested-tier annotation only.
- Render sidecar request-log Transport cells from the persisted transport protocol using the existing standard labels, such as `HTTP`.
- Render the request-details Transport field with the same standard transport labels while keeping Source as the separate diagnostic field.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `frontend-architecture`: Request-log sidecar row presentation in the dashboard.

## Impact

- Affects `frontend/src/features/dashboard/components/recent-requests-table.tsx`.
- Updates the focused Request Logs component test.
- Adds no dependencies, database changes, or API schema changes.
