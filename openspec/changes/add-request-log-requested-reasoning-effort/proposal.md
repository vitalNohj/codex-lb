## Why

The request-logs table renders a single `reasoning_effort` per row, but that value is captured from the payload *after* `apply_api_key_enforcement()` has already overwritten it, so it always shows the final/enforced effort (e.g. `xhigh`) and never what the client actually asked for. Operators cannot tell from the dashboard whether Cursor sent `medium` or `high` before the API key forced it to `xhigh` — that original value survives only transiently in an INFO log line. This mirrors the existing requested-vs-actual service-tier treatment, which already persists both values and shows the requested one when it differs.

## What Changes

- Persist the client-requested reasoning effort separately from the effective effort on each request log: add a nullable `requested_reasoning_effort` column to `request_logs`, keeping the existing `reasoning_effort` as the effective/forwarded value.
- Capture the original effort before `apply_api_key_enforcement` / alias normalization mutates it, and thread it through to request-log creation alongside the enforced value on the Responses, websocket, HTTP-bridge, streaming-retry, and compact logging paths.
- Backfill is not required for historical rows; `requested_reasoning_effort` stays `NULL` for pre-migration logs (treated as "unknown / same as effective").
- Expose the requested effort in the `GET /api/request-logs` response and render it in the dashboard recent-requests table as `requested → effective` (e.g. `medium → xhigh`) only when the two differ, matching the requested-service-tier display pattern.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `responses-api-compat`: Request logs persist the client-requested reasoning effort separately from the effective/enforced effort.
- `frontend-architecture`: The dashboard request-log API exposes the requested reasoning effort and the recent-requests UI shows it when it differs from the effective effort.

## Impact

- Schema: new nullable `request_logs.requested_reasoning_effort` column plus a single-head Alembic revision (`upgrade`/`downgrade`); no backfill.
- Backend: `app/db/models.py`, the new migration, `app/modules/proxy/request_policy.py` (return/expose the pre-enforcement effort), the request-log creation helpers in `app/modules/proxy/_service/{request_log.py,support.py,request_log paths}` and the call sites in `streaming/mixin.py`, `websocket/mixin.py`, `http_bridge/request_submit.py`, `streaming/retry.py`, and `compact.py`, plus `app/modules/request_logs/{schemas,mappers,service,repository}.py`.
- Frontend: `frontend/src/features/dashboard` request-logs table and its row schema/mapping.
- No new public API endpoints, no new dependencies. Backend change requires a service restart to take effect (not performed unprompted).
