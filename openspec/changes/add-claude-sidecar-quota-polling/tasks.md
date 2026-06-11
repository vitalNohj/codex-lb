## 1. Existing status-only foundation

- [x] 1.1 Enable CLIProxyAPI Management API and capture `tests/fixtures/claude_sidecar_auth_files.json`.
- [x] 1.2 Persist encrypted Management API key and quota poll interval.
- [x] 1.3 Add `ClaudeSidecarClient.list_auth_files()` and quota snapshot parsing.
- [x] 1.4 Add `ClaudeSidecarQuotaPoller` and wire it into app lifespan.
- [x] 1.5 Surface hard Claude sidecar status on accounts, dashboard overview, quota endpoint, and settings UI.

## 2. OpenSpec usage-estimate scope

- [x] 2.1 Update proposal/context/spec to describe `/usage-queue` collection, per-auth plan settings, and estimated 5-hour/weekly percentages.
- [x] 2.2 Validate `openspec validate add-claude-sidecar-quota-polling --strict`.

## 3. Database and settings shape

- [x] 3.1 Add `claude_sidecar_usage_events` model/table with sanitized usage queue fields and indexes.
- [x] 3.2 Add `claude_sidecar_auth_plans_json`, `claude_sidecar_usage_poll_interval_seconds`, `claude_sidecar_usage_queue_batch_size`, and `claude_sidecar_usage_collection_enabled` to `dashboard_settings`.
- [x] 3.3 Add an Alembic revision with upgrade and downgrade.
- [x] 3.4 Extend backend settings repository, schemas, service, and API mapping.
- [x] 3.5 Add settings tests for per-auth plans and collector controls.

## 4. Usage queue client and parser

- [x] 4.1 Add `ClaudeSidecarClient.pop_usage_queue(count)`.
- [x] 4.2 Add typed usage queue parser that ignores raw `api_key`.
- [x] 4.3 Add unit tests for client behavior and parser edge cases.

## 5. Usage collector and repository

- [x] 5.1 Add repository methods to insert usage events, skip duplicates, and query window totals.
- [x] 5.2 Add single-leader background collector gated on sidecar enabled, Management key, and collection enabled.
- [x] 5.3 Wire collector start/stop into app lifespan.
- [x] 5.4 Add unit tests for gating, duplicate handling, bounded drains, and error swallowing.

## 6. Estimate math

- [x] 6.1 Add plan presets and custom per-auth budget parsing.
- [x] 6.2 Calculate active 5-hour and weekly windows from persisted events.
- [x] 6.3 Calculate per-auth and aggregate remaining percentages from total tokens and budgets.
- [x] 6.4 Clamp estimates when auth-files reports hard quota exceeded.
- [x] 6.5 Add unit tests for normal, missing-plan, over-budget, exceeded, and rollover cases.

## 7. Backend API surface

- [x] 7.1 Extend `SidecarAuthAccount` with auth index, plan metadata, token counts, budgets, estimate percentages, reset times, and confidence.
- [x] 7.2 Populate synthetic account `usage`, window minutes, resets, and per-auth estimate rows.
- [x] 7.3 Extend `/api/claude-sidecar/quota` with estimate fields.
- [x] 7.4 Add integration tests for `/api/accounts`, `/api/dashboard/overview`, and `/api/claude-sidecar/quota`.

## 8. Frontend settings and account UI

- [x] 8.1 Extend frontend schemas and settings payload mapping.
- [x] 8.2 Add per-auth plan/budget controls to Claude sidecar settings.
- [x] 8.3 Render estimated 5-hour and weekly bars on synthetic dashboard card.
- [x] 8.4 Render estimated rows on account list and account detail.
- [x] 8.5 Exclude synthetic usage from dashboard aggregates even when `usage` is populated.
- [x] 8.6 Update frontend mocks and targeted tests.

## 9. Verification

- [x] 9.1 Run strict OpenSpec validation.
- [x] 9.2 Run targeted backend unit and integration tests.
- [x] 9.3 Run frontend typecheck and targeted Vitest files.
- [x] 9.4 Run changed-file lint checks.
- [x] 9.5 Perform live smoke if local services are available.
