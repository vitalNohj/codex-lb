## 1. Database and request-log model

- [ ] 1.1 Add nullable `requested_reasoning_effort` to `RequestLog` in `app/db/models.py`, adjacent to `reasoning_effort`.
- [ ] 1.2 Add a new Alembic revision that adds/drops `request_logs.requested_reasoning_effort` with no historical backfill.
- [ ] 1.3 Update migration tests or schema checks as needed so the new column is covered by the database validation path.

## 2. Backend request-log persistence

- [ ] 2.1 Add `requested_reasoning_effort` to request-log write/persist helper signatures in `app/modules/proxy/_service/request_log.py`, keeping it adjacent to `reasoning_effort`.
- [ ] 2.2 Add `requested_reasoning_effort` to `RequestLogRepository.create()` and persist it on new rows.
- [ ] 2.3 Add `requested_reasoning_effort` to the in-flight request state objects that later finalize websocket/HTTP-bridge logs.
- [ ] 2.4 Thread `requested_reasoning_effort` through all request-log call sites that already pass `reasoning_effort`, including streaming, retry error, websocket, HTTP bridge, compact, warmup, and local error paths.

## 3. Requested-effort capture

- [ ] 3.1 Add a small request-policy helper or return value that captures the client-sent reasoning effort before `apply_api_key_enforcement()` mutates the payload.
- [ ] 3.2 Use the captured value on native Responses request paths before enforcement, preserving `None` when the client sent no effort.
- [ ] 3.3 Ensure chat-completions-to-Responses conversion preserves top-level `reasoning_effort` or nested `reasoning.effort` before enforcement so Cursor custom-model traffic records the requested value.
- [ ] 3.4 Keep `reasoning_effort` as the effective/forwarded value after enforcement and alias normalization.

## 4. Request-log API and dashboard UI

- [ ] 4.1 Add `requested_reasoning_effort` to `RequestLogEntry` and map it from `RequestLog`.
- [ ] 4.2 Add `requestedReasoningEffort` to the frontend request-log schema, mocks, and factories.
- [ ] 4.3 Update the recent-requests table model cell to render effective effort in the main model label and show `Requested <effort>` only when `requestedReasoningEffort` is non-null and differs from `reasoningEffort`.
- [ ] 4.4 Keep existing request-log model options and effort filters based on effective `reasoningEffort`.

## 5. Tests

- [ ] 5.1 Add backend tests proving `requested_reasoning_effort` and effective `reasoning_effort` are persisted separately when API-key enforcement raises the effort.
- [ ] 5.2 Add backend tests for matching requested/effective effort, omitted client effort, and enforcement-injected effort from a missing client value.
- [ ] 5.3 Add request-log API/schema tests proving `requestedReasoningEffort` is serialized and legacy/null rows remain valid.
- [ ] 5.4 Add frontend table tests proving differing requested/effective effort renders the requested annotation and matching/null requested effort does not.

## 6. Validation

- [ ] 6.1 Run `openspec validate add-request-log-requested-reasoning-effort --strict` and `openspec validate --specs`.
- [ ] 6.2 Run `uv run codex-lb-db upgrade head` and `uv run codex-lb-db check`.
- [ ] 6.3 Run targeted backend tests for request-log persistence/API behavior.
- [ ] 6.4 Run targeted frontend tests for request-log schemas and recent-requests table behavior.
- [ ] 6.5 Run relevant lint/type checks for touched backend and frontend files.
