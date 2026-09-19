## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, design, context, tasks, and delta specs for NVIDIA sidecar routing.
- [ ] 1.2 Validate `add-nvidia-sidecar-routing` with `uv run openspec validate add-nvidia-sidecar-routing --strict`.

## 2. Database and env defaults

- [x] 2.1 Add NVIDIA columns to `DashboardSettings`, including default reasoning effort.
- [x] 2.2 Create an idempotent Alembic migration parented on the live head, prefix JSON server default `[]`, `enabled=false`, base URL `https://integrate.api.nvidia.com/v1`. Downgrade drops only the new columns.
- [x] 2.3 Add env defaults in `app/core/config/settings.py` and `.env.example`.
- [x] 2.4 Seed prefixes in the settings repository create path from `CODEX_LB_NVIDIA_SIDECAR_MODEL_PREFIXES` (empty by default).

## 3. Settings module

- [x] 3.1 Add NVIDIA fields to schemas, service, repository, and API.
- [x] 3.2 Encrypt, clear, and redact the API key.
- [x] 3.3 Include NVIDIA in prefix/full-model uniqueness validation.
- [x] 3.4 Add uniqueness tests covering OpenRouter full-model collisions.

## 4. HTTP client

- [x] 4.1 Copy `openrouter_sidecar.py` to `nvidia_sidecar.py` (aiohttp GET /models + POST /chat/completions).
- [x] 4.2 Send User-Agent and Bearer key. Default `owned_by` is `nvidia`. Do not copy OrcaRouter cost/referer headers.
- [x] 4.3 Add unit tests for headers, models parse, errors, and cache.
- [x] 4.4 Record parsed prices under `provider="nvidia"` when present; omit invented prices.

## 5. Dispatch and routing

- [x] 5.1 Copy OpenRouter dispatch to `nvidia_sidecar_dispatch.py`.
- [x] 5.2 Set `SIDECAR_PROVIDER_ORDER` to `("claude", "openrouter", "nvidia", "orcarouter", "omniroute", "ollama", "opencode_go")`.
- [x] 5.3 Wire Chat Completions after OpenRouter. Do not dispatch `/v1/responses`.
- [x] 5.4 Preserve DeepSeek V4 repair and true effort override.
- [x] 5.5 Merge configured full models into `/v1/models` with `owned_by: nvidia`.
- [x] 5.6 Add unit and integration tests.

## 6. Dashboard API

- [x] 6.1 Copy `app/modules/openrouter_sidecar/` to `app/modules/nvidia_sidecar/`.
- [x] 6.2 Mount `/api/nvidia-sidecar` and add dependency context.
- [x] 6.3 Missing key skips network and reports `missing_api_key`.
- [x] 6.4 Add dashboard API integration tests.

## 7. Accounts and request logs

- [x] 7.1 Copy OpenRouter synthetic summary. Display name `NVIDIA`, `account_id` `nvidia-sidecar`, source `nvidia_sidecar`.
- [x] 7.2 Wire dashboard and accounts synthetics.
- [x] 7.3 Add an explicit `nvidia` branch in synthetic account UI (not Claude fallback).
- [x] 7.4 Label request logs `NVIDIA` / HTTP.

## 8. Frontend

- [x] 8.1 Add `nvidiaSidecar*` schemas, payload, API, hooks, and MSW handlers.
- [x] 8.2 Copy OpenRouter settings UI; enable toggle above callout; prefilled NVIDIA base URL; docs link with `noopener noreferrer`.
- [x] 8.3 Add one NVIDIA tab after OpenRouter and before OrcaRouter.
- [x] 8.4 Extend `SidecarIntegrationId`, names, and `integrationValues`.
- [x] 8.5 Update effort select, request-log labels, and every `BASE_SETTINGS` fixture.
- [x] 8.6 Add the `nvidia` dashboard account-type filter key (after OpenRouter, before OrcaRouter).

## 9. Verification

- [ ] 9.1 `uv run openspec validate add-nvidia-sidecar-routing --strict`
- [ ] 9.2 `uv run pytest` on the new unit/integration tests plus `test_settings_service.py` uniqueness and `test_sidecar_routing.py`
- [ ] 9.3 From `frontend/`: targeted vitest including `sidecar-integrations-card.test.tsx`, then `bun run build`
- [ ] 9.4 Do not restart systemd. Do not run the full suite unprompted.
