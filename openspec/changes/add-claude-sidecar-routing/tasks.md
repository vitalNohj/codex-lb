## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, context, tasks, and delta specs for Claude sidecar routing.
- [x] 1.2 Update proposal, context, tasks, and delta specs for dashboard-managed sidecar UI.
- [ ] 1.3 Validate OpenSpec artifacts locally.

## 2. Sidecar operator setup documentation

- [x] 2.1 Capture CLIProxyAPI install, OAuth, config, and verification steps in change context.
- [x] 2.2 Capture Cursor custom model and public base URL setup in change context.

## 3. Env settings

- [x] 3.1 Add env-only `CODEX_LB_CLAUDE_SIDECAR_*` settings.
- [x] 3.2 Document the env settings in `.env.example`.

## 4. Sidecar client

- [x] 4.1 Add the async CLIProxyAPI sidecar HTTP client.
- [x] 4.2 Add cached model-list fetching with last-good fallback.

## 5. Chat-completions routing

- [x] 5.1 Add sidecar model-prefix detection.
- [x] 5.2 Add non-streaming sidecar chat-completions forwarding.
- [x] 5.3 Add streaming SSE sidecar forwarding with usage extraction.
- [x] 5.4 Add sidecar error mapping into OpenAI-compatible envelopes.
- [x] 5.5 Wire the sidecar branch into `/v1/chat/completions` without changing the existing Codex path.

## 6. Model catalog

- [x] 6.1 Merge sidecar models into OpenAI-compatible `/v1/models`.
- [x] 6.2 Keep Codex-native `/backend-api/codex/models` unchanged.
- [x] 6.3 Preserve per-key filtering and deduplicate model IDs.

## 7. API-key reservations and logging

- [x] 7.1 Settle sidecar reservations from sidecar usage when available.
- [x] 7.2 Release sidecar reservations on errors, missing usage, and stream disconnects.
- [x] 7.3 Add request-log coverage if the sidecar branch would otherwise be invisible.

## 8. Tests and verification

- [x] 8.1 Add unit tests for the sidecar client.
- [x] 8.2 Add unit tests for sidecar dispatch helpers and SSE usage extraction.
- [x] 8.3 Add integration tests for chat routing, streaming, errors, model filtering, and Codex-path regression.
- [x] 8.4 Run targeted tests and full lint/test verification.

## 9. Dashboard-managed sidecar settings

- [ ] 9.1 Persist sidecar settings on `dashboard_settings`, including enabled flag, base URL, encrypted API key, model prefixes, timeouts, model cache TTL, and health fields.
- [ ] 9.2 Add dashboard settings schemas, service, repository, and API support for saving sidecar settings without returning the raw API key.
- [ ] 9.3 Make sidecar routing and model merging read the effective dashboard sidecar configuration at request time.

## 10. Sidecar dashboard APIs

- [ ] 10.1 Add dashboard-authenticated sidecar status, test-connection, and model-list endpoints.
- [ ] 10.2 Record last sidecar health check status, time, model count, and error message on test.
- [ ] 10.3 Ensure sidecar dashboard API errors never expose the sidecar API key.

## 11. Synthetic account and dashboard UI

- [ ] 11.1 Append one read-only synthetic Claude sidecar account to `/api/accounts` when sidecar config exists or is enabled.
- [ ] 11.2 Render the synthetic account in the Accounts UI with status, base URL, model count, last check, and read-only actions.
- [ ] 11.3 Add Settings UI for enabling, configuring, saving, clearing the API key, testing the connection, and viewing sidecar models.
- [ ] 11.4 Include sidecar models in dashboard API-key model controls when enabled.
- [ ] 11.5 Make dashboard request logs clearly identify `claude_sidecar` traffic.

## 12. Dashboard tests and verification

- [ ] 12.1 Add backend tests for settings persistence, key redaction/clearing, sidecar status/test, synthetic account, `/api/models`, and routing config.
- [ ] 12.2 Add frontend tests for sidecar settings, synthetic account read-only behavior, model picker entries, and request-log source display.
- [ ] 12.3 Run targeted backend/frontend tests, lint touched code, and manually verify CLIProxyAPI up/down behavior.
