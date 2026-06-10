## 1. CLIProxyAPI Management API enablement (ops)

- [x] 1.1 Generate a Management API secret and add `remote-management.secret-key` to `~/.cli-proxy-api/config.yaml`.
- [x] 1.2 Restart `cli-proxy-api.service` and confirm `GET /v0/management/auth-files` returns the Claude entry.
- [x] 1.3 Capture the live response as `tests/fixtures/claude_sidecar_auth_files.json` for parser tests.
- [x] 1.4 Verify wrong/missing key returns 401 (unauthorized branch).

## 2. Database migration

- [ ] 2.1 Add `claude_sidecar_management_key_encrypted`, `claude_sidecar_quota_poll_interval_seconds`, `claude_sidecar_quota_state_json`, `claude_sidecar_quota_checked_at` columns to `dashboard_settings`.
- [ ] 2.2 Add Alembic revision `20260611_000000_add_claude_sidecar_quota_polling` chained off the current head with matching `downgrade()`.
- [ ] 2.3 Verify single Alembic head and upgrade/downgrade round-trip succeed.

## 3. Settings plumbing

- [ ] 3.1 Add env defaults `claude_sidecar_management_key` and `claude_sidecar_quota_poll_interval_seconds` in `app/core/config/settings.py`.
- [ ] 3.2 Extend `SettingsRepository.get_or_create()` and `update()` with the new columns (encrypted Management key, interval, snapshot, checked-at).
- [ ] 3.3 Extend `DashboardSettingsResponse` and `DashboardSettingsUpdateRequest` schemas with `_configured` flag, interval, write-only Management key, and clear flag.
- [ ] 3.4 Extend `SettingsService` to encrypt/decrypt the Management key and expose the new fields in `SettingsData` / `_to_data`.
- [ ] 3.5 Wire new fields into `settings/api.py` response builder and PUT merge block (audit-safe; never returns the raw Management key).
- [ ] 3.6 Add integration test mirroring the existing API-key save/redact/preserve/clear case.

## 4. Management client + quota snapshot module

- [ ] 4.1 Add `management_key` to `ClaudeSidecarConfig` and pass it through `sidecar_config_from_settings()`.
- [ ] 4.2 Add `ClaudeSidecarClient.list_auth_files()` with error mapping matching `list_models`.
- [ ] 4.3 Create `app/modules/claude_sidecar/quota.py` with `SidecarAuthQuota`, `SidecarQuotaSnapshot`, `parse_auth_files`, `snapshot_to_json`, `snapshot_from_json`.
- [ ] 4.4 Add unit tests using `tests/fixtures/claude_sidecar_auth_files.json` covering parser, status, and round-trip.

## 5. Quota poller scheduler

- [ ] 5.1 Create `app/modules/claude_sidecar/quota_poller.py` with `ClaudeSidecarQuotaPoller` and factory.
- [ ] 5.2 Implement `_poll_once` with the documented gating + status classification + snapshot write + cache invalidation.
- [ ] 5.3 Wire start/stop into `app/main.py` lifespan alongside other schedulers.
- [ ] 5.4 Add unit tests covering enabled/disabled/unauthorized/unreachable branches.

## 6. Backend account/dashboard/quota surface

- [ ] 6.1 Extract `build_claude_sidecar_summary` into `app/modules/accounts/sidecar_summary.py` and call it from `AccountsService`.
- [ ] 6.2 Enrich the summary with snapshot-driven `status`, `reset_at_primary`, `last_refresh_at`, and `sidecar_auths`.
- [ ] 6.3 Add `SidecarAuthAccount` to `accounts/schemas.py` and append `sidecar_auths` to `AccountSummary`.
- [ ] 6.4 Include the synthetic account in `DashboardService.get_overview()` (appended after sorting).
- [ ] 6.5 Add `ClaudeSidecarQuotaResponse` schema and `GET /api/claude-sidecar/quota` endpoint.
- [ ] 6.6 Extend integration tests: `/api/accounts` quota mapping (some/all exceeded), `/api/dashboard/overview` synthetic-account inclusion, and `/api/claude-sidecar/quota` shape.

## 7. Frontend accounts + dashboard

- [ ] 7.1 Add `SidecarAuthAccountSchema` and extend `AccountSummarySchema` with `sidecarAuths`.
- [ ] 7.2 Extend accounts schema test for `rate_limited` plus `sidecarAuths` parsing.
- [ ] 7.3 Update `account-list-item.tsx` synthetic branch with a Quota row.
- [ ] 7.4 Update `account-detail.tsx` `SyntheticAccountDetail` with Quota + Last quota check rows and per-auth list.
- [ ] 7.5 Add `SyntheticAccountCard` in `dashboard/components/account-card.tsx` and branch on `account.synthetic`.
- [ ] 7.6 Extend frontend tests (account detail + dashboard card).

## 8. Frontend settings

- [ ] 8.1 Update `settings/schemas.ts` and update-request types with the new Management key fields and poll interval.
- [ ] 8.2 Update `buildSettingsUpdateRequest` to map the new camelCase fields to snake_case.
- [ ] 8.3 Add Management key inputs and quota status row in `claude-sidecar-settings.tsx`.
- [ ] 8.4 Add `useClaudeSidecarQuota()` hook and wire MSW handlers in tests.
- [ ] 8.5 Extend `claude-sidecar-settings.test.tsx` for save/clear/configured states.

## 9. Verification

- [ ] 9.1 Full backend `uv run pytest -q` green.
- [ ] 9.2 `uv run ruff check .` clean.
- [ ] 9.3 `cd frontend && bun run build` clean (no type errors) and `bun run test` green.
- [ ] 9.4 Live smoke: restart codex-lb, save Management key, observe `/api/claude-sidecar/quota` healthy after one interval.
- [ ] 9.5 Negative live smoke: stop sidecar → `unreachable`; restart → `healthy`.
- [ ] 9.6 `uv run openspec validate add-claude-sidecar-quota-polling --strict` passes.
- [ ] 9.7 Sync delta to main specs and run `uv run openspec validate --specs`.
