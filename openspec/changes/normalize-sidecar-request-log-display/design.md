## Context

The Recent Requests table already receives `source` and `transport` as separate request-log fields. Sidecar rows currently use `source` to add a sidecar badge beneath the Model value and to override the Transport field with `Sidecar HTTP`, even when `transport` is simply `http`.

## Goals / Non-Goals

**Goals:**

- Keep the request-log table compact by removing sidecar-only decoration from the Model cell.
- Display the persisted transport protocol using the same labels as regular request rows.
- Preserve Source in request details for diagnostics.

**Non-Goals:**

- Change request-log API schemas, persisted request-log values, or sidecar routing behavior.
- Rename sidecar account labels in the Account column.
- Remove diagnostic Source information from the details dialog.

## Decisions

- Reuse the existing `TRANSPORT_LABELS` and `TRANSPORT_CLASS_MAP` path for sidecar rows instead of adding a sidecar-specific branch.
- Keep `sidecarSourceLabel` for account labeling and the details Source field.
- Update the focused component test to assert sidecar rows show the model and `HTTP` without the extra sidecar model badge or `Sidecar HTTP` label.

## Risks / Trade-offs

- Operators lose the redundant sidecar marker in the compact Model cell. The Account column and details Source field still identify the sidecar path when needed.
