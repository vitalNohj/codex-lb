## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, context, tasks, and delta specs for OpenRouter sidecar routing.
- [x] 1.2 Validate OpenSpec artifacts locally.

## 2. Database and env defaults

- [x] 2.1 Add OpenRouter sidecar columns to `DashboardSettings`.
- [x] 2.2 Create Alembic migration.
- [x] 2.3 Add env defaults in `app/core/config/settings.py` and `.env.example`.
- [x] 2.4 Wire seeding in settings repository.

## 3. Settings module

- [x] 3.1 Add OpenRouter fields to settings schemas, service, repository, and API.

## 4. OpenRouter client

- [x] 4.1 Add `app/core/clients/openrouter_sidecar.py`.
- [x] 4.2 Add unit tests for the client.

## 5. Dispatch and routing

- [x] 5.1 Add `app/modules/proxy/openrouter_sidecar_dispatch.py`.
- [x] 5.2 Wire OpenRouter branch into `/v1/chat/completions` after Claude sidecar check.
- [x] 5.3 Merge OpenRouter models into `/v1/models` and dashboard `/api/models`.
- [x] 5.4 Add unit and integration tests.

## 6. Dashboard OpenRouter sidecar API

- [x] 6.1 Add `app/modules/openrouter_sidecar/service.py` and `api.py`.
- [x] 6.2 Mount router and add dependency wiring.
- [x] 6.3 Add integration tests.

## 7. Synthetic OpenRouter account

- [x] 7.1 Add `openrouter_sidecar_summary.py` and wire into accounts service.
- [x] 7.2 Add accounts API integration test coverage.

## 8. Request logs and pricing

- [x] 8.1 Log with `source=openrouter_sidecar`.
- [x] 8.2 Add frontend request log label.
- [x] 8.3 Add initial OpenRouter pricing entries.

## 9. Frontend

- [x] 9.1 Add OpenRouter settings schemas, hooks, and API paths.
- [x] 9.2 Add `openrouter-sidecar-settings.tsx` and embed in settings page.
- [x] 9.3 Update account detail/card for OpenRouter synthetic account.
- [x] 9.4 Add frontend tests.

## 10. Final verification

- [x] 10.1 Run `uv run pytest`, `uv run ruff check`, and `openspec validate --strict`.
