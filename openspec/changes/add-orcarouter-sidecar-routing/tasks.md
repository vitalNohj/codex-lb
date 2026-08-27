## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, design, context, tasks, and delta specs for OrcaRouter sidecar routing.
- [x] 1.2 Validate `add-orcarouter-sidecar-routing` with `uv run openspec validate add-orcarouter-sidecar-routing --strict`.

## 2. Database and env defaults

- [x] 2.1 Add OrcaRouter columns to `DashboardSettings`.
- [x] 2.2 Create an idempotent Alembic migration parented on the live head, seeded `orcarouter/` strip-off, `enabled=false`. Downgrade drops only the new columns.
- [x] 2.3 Add env defaults in `app/core/config/settings.py` and `.env.example`.
- [x] 2.4 Seed prefixes in the settings repository create path.

## 3. Settings module

- [x] 3.1 Add OrcaRouter fields to schemas, service, repository, and API.
- [x] 3.2 Encrypt, clear, and redact the API key.
- [x] 3.3 Include OrcaRouter in prefix/full-model uniqueness validation.
- [x] 3.4 Add uniqueness tests covering OmniRoute `orcarouter/` collisions.

## 4. HTTP client

- [x] 4.1 Copy `openrouter_sidecar.py` to `orcarouter_sidecar.py` (aiohttp GET /models + POST /chat/completions).
- [x] 4.2 Send User-Agent, HTTP-Referer, X-Title, and Bearer key. Default `owned_by` is `orcarouter`.
- [x] 4.3 Add unit tests for headers, models parse, errors, and cache.

## 5. Dispatch and routing

- [x] 5.1 Copy OpenRouter dispatch to `orcarouter_sidecar_dispatch.py`.
- [x] 5.2 Set `SIDECAR_PROVIDER_ORDER` to `("claude", "openrouter", "orcarouter", "omniroute", "ollama")`.
- [x] 5.3 Wire Chat Completions after OpenRouter. Do not dispatch `/v1/responses`.
- [x] 5.4 Preserve DeepSeek V4 repair and true effort override. Forward `orcarouter/auto` unstripped.
- [x] 5.5 Merge configured full models into `/v1/models` with `owned_by: orcarouter`.
- [x] 5.6 Add unit and integration tests.

## 6. Dashboard API

- [x] 6.1 Copy `app/modules/openrouter_sidecar/` to `app/modules/orcarouter_sidecar/`.
- [x] 6.2 Mount `/api/orcarouter-sidecar` and add dependency context.
- [x] 6.3 Missing key skips network and reports `missing_api_key`.
- [x] 6.4 Add dashboard API integration tests.

## 7. Accounts and request logs

- [x] 7.1 Copy OpenRouter synthetic summary. Display name `OrcaRouter`, `account_id` `orcarouter-sidecar`, source `orcarouter_sidecar`.
- [x] 7.2 Wire dashboard and accounts synthetics.
- [x] 7.3 Add an explicit `orcarouter` branch in synthetic account UI (not Claude fallback).
- [x] 7.4 Label request logs `OrcaRouter` / HTTP.

## 8. Frontend

- [x] 8.1 Add `orcarouterSidecar*` schemas, payload, API, hooks, and MSW handlers.
- [x] 8.2 Copy OpenRouter settings UI; enable toggle above callout; OmniRoute prefix warning; external links with `noopener noreferrer`.
- [x] 8.3 Add one OrcaRouter tab after OpenRouter.
- [x] 8.4 Extend `SidecarIntegrationId`, names, and `integrationValues`.
- [x] 8.5 Update effort select, request-log labels, and every `BASE_SETTINGS` fixture.
- [x] 8.6 Add the `orcarouter` dashboard account-type filter key (after OpenRouter, before Omniroute) and classify a provider-less Claude synthetic as `cliproxy`.

## 9. Verification

- [x] 9.1 `uv run openspec validate add-orcarouter-sidecar-routing --strict`
- [x] 9.2 `uv run pytest` on the new unit/integration tests plus `test_settings_service.py` uniqueness
- [x] 9.3 From `frontend/`: targeted vitest including `sidecar-integrations-card.test.tsx`, then `bun run build`
- [x] 9.4 Do not restart systemd. Do not run the full suite unprompted.
