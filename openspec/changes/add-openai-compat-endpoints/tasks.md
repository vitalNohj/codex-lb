## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, design, context, tasks, and delta specs for generic OpenAI-compat endpoints.
- [x] 1.2 Validate `add-openai-compat-endpoints` with `uv run openspec validate add-openai-compat-endpoints --strict`.

## 2. Database

- [x] 2.1 Add `openai_compat_endpoints_json` to `DashboardSettings` with Python and server default `[]`.
- [x] 2.2 Create an idempotent Alembic migration parented on `20260916_010000_add_nvidia_sidecar_dashboard_settings`. Downgrade drops only the new column.

## 3. Settings module

- [x] 3.1 Add `openaiCompatEndpoints` to schemas, service, repository, and API.
- [x] 3.2 Encrypt, clear, and redact per-endpoint API keys inside the JSON blob.
- [x] 3.3 Include every endpoint in prefix/full-model uniqueness validation.
- [x] 3.4 Reject duplicate names, blank name/URL, more than 32 endpoints, and non-http(s) URLs.

## 4. HTTP client and dispatch

- [x] 4.1 Add a generic aiohttp client (`GET /models`, `POST /chat/completions`) with optional Bearer key.
- [x] 4.2 Add dispatch parameterized by endpoint id. Chat Completions only. DeepSeek V4 repair and true effort override.
- [x] 4.3 Load enabled endpoints into routing entries with `provider=openai_compat:{uuid}`. Dispatch that prefix before the OmniRoute fallback.
- [x] 4.4 Merge configured full models into `/v1/models` with `owned_by: openai_compat`.
- [x] 4.5 Record parsed prices under `openai_compat:{uuid}` when present; omit invented prices; do not treat echoed cost as billed.

## 5. Dashboard API, accounts, logs

- [x] 5.1 Mount `/api/openai-compat/{endpoint_id}/status|test|models`.
- [x] 5.2 One synthetic account per endpoint: `account_id openai-compat-{uuid}`, `provider openai_compat`, display name = operator name.
- [x] 5.3 Request logs use `source=openai_compat:{uuid}` and `transport=http`. UI label is the operator name.

## 6. Frontend

- [x] 6.1 Add `openaiCompatEndpoints` schemas, payload, API, hooks, and MSW handlers. Update every `BASE_SETTINGS` fixture.
- [x] 6.2 Add a `+` control that creates a named tab (Name + Base URL dialog).
- [x] 6.3 Per-endpoint OpenRouter-shaped card with Remove. Uniqueness includes the list.
- [x] 6.4 Explicit `openai_compat` synthetic-account branch, effort override per endpoint, dashboard filter key `openai_compat`.

## 7. Verification

- [x] 7.1 `uv run openspec validate add-openai-compat-endpoints --strict`
- [x] 7.2 `uv run pytest` on the new unit/integration tests plus uniqueness and `test_sidecar_routing.py`
- [x] 7.3 From `frontend/`: targeted vitest including the integrations card, then `bun run build`
- [x] 7.4 Do not restart systemd. Do not run the full suite unprompted.
