## 1. OpenSpec artifacts

- [ ] 1.1 Create proposal, design, tasks, and delta specs for Ollama Cloud sidecar routing.
- [ ] 1.2 Validate `add-ollama-sidecar-routing` with strict OpenSpec validation.

## 2. Database settings

- [ ] 2.1 Add Ollama sidecar columns to `DashboardSettings`.
- [ ] 2.2 Create Alembic migration with upgrade and downgrade coverage.
- [ ] 2.3 Verify the migration sits on the current intended parent and preserves existing dashboard settings.

## 3. Settings module

- [ ] 3.1 Add Ollama fields to settings schemas, service data contracts, repository update paths, and API responses.
- [ ] 3.2 Encrypt, clear, and redact the Ollama API key using the existing sidecar key-handling pattern.
- [ ] 3.3 Add Ollama to cross-integration prefix and full-model uniqueness validation.
- [ ] 3.4 Add settings API and service tests for round-trip, redaction, clearing, validation, and route conflicts.

## 4. Ollama SDK dependency

- [ ] 4.1 Add the official `ollama` Python package with `uv add ollama`.
- [ ] 4.2 Confirm the package imports from the project virtual environment.

## 5. Ollama client wrapper

- [ ] 5.1 Add `app/core/clients/ollama_sidecar.py`.
- [ ] 5.2 Implement config, error types, model discovery, cloud filtering, cache behavior, non-stream chat, and streaming chat.
- [ ] 5.3 Add unit tests for cloud filtering, cache behavior, SDK error conversion, transport failures, and streaming chunks.

## 6. Chat Completions adapter

- [ ] 6.1 Add `app/modules/proxy/ollama_sidecar_dispatch.py`.
- [ ] 6.2 Implement config loading, routing entry construction, OpenAI-to-Ollama payload conversion, non-stream response conversion, streaming SSE conversion, reservation settlement/release, request logging, and cost-null handling.
- [ ] 6.3 Add dispatch unit tests for content, tool calls, usage, streaming, upstream errors, reservation release, and request-log fields.

## 7. Unified routing

- [ ] 7.1 Add Ollama to the unified sidecar provider order.
- [ ] 7.2 Wire Ollama into `/v1/chat/completions` routing after API-key model validation and before native Codex account selection.
- [ ] 7.3 Add routing tests for full models, prefixes, stripped wire models, disabled fallthrough, enforced models, and allowed-model restrictions.

## 8. Dashboard API

- [ ] 8.1 Add `app/modules/ollama_sidecar/` API, schemas, and service.
- [ ] 8.2 Add dependency wiring and router registration.
- [ ] 8.3 Add dashboard API tests for disabled, missing key, successful test connection, unauthorized, and cloud-filtered models.

## 9. Frontend schemas, API calls, and hooks

- [ ] 9.1 Add Ollama settings fields and dashboard response schemas.
- [ ] 9.2 Add Ollama dashboard API calls and `useOllamaSidecar`.
- [ ] 9.3 Add MSW handlers and factory defaults.
- [ ] 9.4 Add frontend schema and payload tests.

## 10. Settings integration tab

- [ ] 10.1 Add `OllamaSidecarSettings` with `bare?: boolean`.
- [ ] 10.2 Add Ollama to `SidecarIntegrationCard` IDs, names, and conflict-value collection.
- [ ] 10.3 Add exactly one Ollama entry to the existing `tabs` array in `sidecar-integrations.tsx`.
- [ ] 10.4 Add frontend tests for the Ollama tab, default active tab behavior, persistence, discovered model add, and duplicate conflicts.

## 11. Model catalog

- [ ] 11.1 Add configured Ollama full models to OpenAI-compatible `/v1/models` when Ollama is enabled.
- [ ] 11.2 Do not advertise discovered-only Ollama models.
- [ ] 11.3 Add model catalog tests for enabled, disabled, discovered-only, and API-key-filtered cases.

## 12. Accounts and request logs

- [ ] 12.1 Add an Ollama synthetic account summary.
- [ ] 12.2 Wire Ollama into Accounts service output.
- [ ] 12.3 Ensure Ollama request-log rows display as normal HTTP rows with provider/account label `Ollama`.
- [ ] 12.4 Add backend or frontend presentation tests where existing label mapping requires them.

## 13. Cost and usage

- [ ] 13.1 Confirm no unsupported Ollama pricing entries are added.
- [ ] 13.2 Record Ollama token usage when present.
- [ ] 13.3 Keep `cost_usd` null unless backed by pricing data.
- [ ] 13.4 Add cost and usage regression tests.

## 14. Backend verification

- [ ] 14.1 Run strict OpenSpec validation.
- [ ] 14.2 Run targeted backend unit and integration tests.
- [ ] 14.3 Run backend linting for changed app and test files.

## 15. Frontend verification

- [ ] 15.1 Run targeted Settings Vitest suites.
- [ ] 15.2 Run frontend typecheck.

## 16. Manual UI checks

- [ ] 16.1 Perform manual UI checks only if the user asks for manual verification and confirms it is safe to run the needed servers.
