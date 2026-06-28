## Context

Request logs currently store one reasoning-effort field, `request_logs.reasoning_effort`. On native Responses traffic that value is read from `payload.reasoning.effort` at request-log write time, after `apply_api_key_enforcement()` and model-alias normalization may have mutated the payload. This makes the stored value useful as the effective/forwarded effort, but it hides the client-requested effort. Operators can only infer the original value from transient `api_key_reasoning_enforced` INFO logs.

The service already has a nearby pattern for service tier: `requested_service_tier`, `actual_service_tier`, and billable `service_tier` are persisted separately, and the dashboard shows the requested tier only when it differs from the visible tier. Reasoning effort should follow that shape without changing request routing or enforcement semantics.

## Goals / Non-Goals

**Goals:**

- Persist the incoming client-requested reasoning effort separately from the effective/forwarded effort.
- Preserve `request_logs.reasoning_effort` as the effective value so existing filters, cost views, and model labels keep their current meaning.
- Capture the requested value before enforcement/alias logic mutates the request.
- Expose `requestedReasoningEffort` through `GET /api/request-logs`.
- Render requested-vs-effective effort in the recent-requests table only when they differ.
- Keep historical logs valid without backfill.

**Non-Goals:**

- Do not change API-key enforcement behavior.
- Do not change model-alias parsing or sidecar default-effort injection semantics.
- Do not add new request-log filters for requested effort in this change.
- Do not reconstruct historical requested efforts from journald logs.
- Do not persist raw request payloads or prompt content.

## Decisions

### Add `requested_reasoning_effort` instead of changing `reasoning_effort`

`reasoning_effort` remains the effective/forwarded value. A new nullable `requested_reasoning_effort` column records the client-requested value before enforcement. This mirrors the requested/effective service-tier design and avoids breaking existing dashboards, model filters, and cost/debugging expectations that already treat `reasoning_effort` as the final value.

Alternative considered: repurpose `reasoning_effort` as requested effort and add `effective_reasoning_effort`. That would be clearer naming in isolation but would silently change existing API/UI semantics and require broader migration work.

### Capture requested effort at the request-policy boundary

The requested value should be captured at the same boundary that currently mutates the payload: before `apply_api_key_enforcement()` calls `normalize_upstream_model_alias()` and applies `api_key.enforced_reasoning_effort`. A small helper or return value can make the pre-enforcement value explicit to call sites. Request-log writers then receive both values: `requested_reasoning_effort` and effective `reasoning_effort`.

Alternative considered: parse the original raw JSON request body at each route. That would duplicate parsing logic across chat/responses/websocket/bridge paths and increase the chance of drift between accepted payload shape and logged payload shape.

### Do not backfill historical rows

The migration adds a nullable column and leaves existing rows as `NULL`. A null requested effort means either the client did not send one or the row predates the field; the UI should not show a requested-effort annotation when the value is null.

Alternative considered: backfill `requested_reasoning_effort = reasoning_effort` for old rows. That would falsely imply knowledge of the original requested value for rows that may have been enforced.

### Keep filter options based on effective effort

Existing request-log model options and reasoning-effort filters continue to use `reasoning_effort`, because that field represents the effective model/effort combination sent upstream and currently drives the dashboard model label. Requested-effort filtering can be added later if operators need it.

Alternative considered: include requested effort in model-option keys. That would make existing filters more complex and would not be required to answer the primary operator question in the request row.

## Risks / Trade-offs

- [Risk] Missing one request-log path would produce rows with an effective effort but no requested effort. -> Mitigation: add tests around the main Responses logging path and update the shared `_write_request_log` / `_persist_request_log` signatures so omissions are visible during typing and review.
- [Risk] Null requested effort is ambiguous for legacy rows versus requests where the client omitted effort. -> Mitigation: intentionally render no requested annotation for null; the field is observational, not billing-critical.
- [Risk] Threading another field through many request-log call sites adds churn. -> Mitigation: follow the existing `requested_service_tier` pattern and keep the new parameter adjacent to `reasoning_effort` everywhere.
- [Risk] Model aliases can inject an effort before API-key enforcement. -> Mitigation: the persisted requested value is defined as the client-sent request effort before alias/enforcement mutation, while `reasoning_effort` remains the final effective value.

## Migration Plan

1. Add a nullable `requested_reasoning_effort` column to `request_logs` in a new Alembic revision with downgrade support.
2. Add the mapped field to `RequestLog`.
3. Thread the field through request-log persistence helpers, repository creation, API schemas, and mappers.
4. Capture the pre-enforcement effort before `apply_api_key_enforcement()` mutates payloads and pass it to request-log writers.
5. Add dashboard schema/UI support for `requestedReasoningEffort`, reusing the existing requested-service-tier annotation pattern.
6. Validate with OpenSpec, migration checks, targeted backend tests, and targeted frontend tests.

Rollback is safe by downgrading the migration after deploying code that no longer reads or writes the column. Historical rows with null requested effort remain valid.

## Open Questions

- None.
