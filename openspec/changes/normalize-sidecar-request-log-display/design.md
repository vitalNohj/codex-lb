## Context

The Recent Requests table already receives `source` and `transport` as separate request-log fields. Sidecar rows currently use `source` to add a sidecar badge beneath the Model value, override the Transport field with `Sidecar HTTP`, and render Account values with provider names that include "sidecar".

Claude sidecar auth identity is not stored directly on `request_logs`, but `claude_sidecar_usage_events` records per-request auth metadata keyed by `request_id`. That gives the dashboard API a no-migration path for exposing a best-effort auth display label when the usage collector has observed the sidecar request.

## Goals / Non-Goals

**Goals:**

- Keep the request-log table compact by removing sidecar-only decoration from the Model cell.
- Display the persisted transport protocol using the same labels as regular request rows.
- Display sidecar Account labels without "sidecar"; include Claude sidecar auth identity when available.
- Preserve Source in request details for diagnostics.

**Non-Goals:**

- Change request-log API schemas, persisted request-log values, or sidecar routing behavior.
- Rename sidecar account labels in the Account column.
- Remove diagnostic Source information from the details dialog.

## Decisions

- Reuse the existing `TRANSPORT_LABELS` and `TRANSPORT_CLASS_MAP` path for sidecar rows instead of adding a sidecar-specific branch.
- Add an optional `sidecarAccountLabel` response field derived from `ClaudeSidecarUsageEvent.source`, falling back to `auth_index`, for Claude request-log rows.
- Keep `sidecarSourceLabel` for the details Source field, but use separate provider display labels for the Account column.
- Update the focused component test to assert sidecar rows show the model and `HTTP` without the extra sidecar model badge or `Sidecar HTTP` label.

## Risks / Trade-offs

- Operators lose the redundant sidecar marker in the compact Model and Account cells. The details Source field still identifies the exact sidecar source when needed.
- Claude auth labels are best effort: rows written before a matching usage event exists will show `CLIProxyAPI` until the request-log API can join to usage metadata.
