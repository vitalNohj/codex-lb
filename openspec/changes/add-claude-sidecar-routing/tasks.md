## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, context, tasks, and delta specs for Claude sidecar routing.
- [ ] 1.2 Validate OpenSpec artifacts locally.

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
