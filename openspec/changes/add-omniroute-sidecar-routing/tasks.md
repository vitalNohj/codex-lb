## 1. OpenSpec artifacts

- [ ] 1.1 Create proposal, context, tasks, and delta specs for OmniRoute sidecar routing.
- [ ] 1.2 Validate OpenSpec artifacts locally.

## 2. Database and env defaults

- [ ] 2.1 Add OmniRoute sidecar columns to `DashboardSettings`.
- [ ] 2.2 Create Alembic migration.
- [ ] 2.3 Add env defaults in `app/core/config/settings.py`.
- [ ] 2.4 Wire seeding in settings repository.

## 3. Settings module

- [ ] 3.1 Add OmniRoute fields to settings schemas, service, repository, and API.

## 4. OmniRoute client

- [ ] 4.1 Add `app/core/clients/omniroute_sidecar.py`.
- [ ] 4.2 Add unit tests for the client.

## 5. Dispatch and routing

- [ ] 5.1 Add `app/modules/proxy/omniroute_sidecar_dispatch.py` with exact selected-model matching.
- [ ] 5.2 Wire OmniRoute branch into `/v1/chat/completions` after Claude and OpenRouter sidecar checks.
- [ ] 5.3 Merge OmniRoute models into `/v1/models` and dashboard `/api/models`.
- [ ] 5.4 Add integration tests for selected-model routing, streaming, and unavailable.

## 6. Dashboard OmniRoute sidecar API

- [ ] 6.1 Add `app/modules/omniroute_sidecar/service.py` and `api.py`.
- [ ] 6.2 Mount router and add dependency wiring.
- [ ] 6.3 Add integration tests.

## 7. Synthetic OmniRoute account

- [ ] 7.1 Add `omniroute_sidecar_summary.py` and wire into accounts/dashboard services.
- [ ] 7.2 Update account detail to label OmniRoute and link to settings anchor.

## 8. Request logs and labels

- [ ] 8.1 Log with `source=omniroute_sidecar`.
- [ ] 8.2 Add frontend request log label `OmniRoute sidecar`.

## 9. Frontend

- [ ] 9.1 Add OmniRoute settings schemas, hooks, and API paths.
- [ ] 9.2 Add `omniroute-sidecar-settings.tsx` with selected-model browser and `Open OmniRoute` link.
- [ ] 9.3 Add OmniRoute to `payload.ts` so saves preserve OmniRoute fields.
- [ ] 9.4 Update MSW handlers and add frontend tests.

## 10. Final verification

- [ ] 10.1 Run `uv run pytest`, `uv run ruff check`, and `openspec validate --strict`.
