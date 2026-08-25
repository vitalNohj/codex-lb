## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, design, tasks, and delta specs for OrcaRouter and OpenCode Free sidecar routing.
- [x] 1.2 Validate `add-orcarouter-and-opencode-sidecar-routing` with `openspec validate add-orcarouter-and-opencode-sidecar-routing --strict`.

## 2. Database settings

- [ ] 2.1 Add OrcaRouter and OpenCode Free sidecar columns to `DashboardSettings`, including enabled, base URL, encrypted API key, prefixes JSON, full models JSON, timeouts, cache TTL, health fields, and default reasoning effort.
- [ ] 2.2 Create one Alembic migration with upgrade and downgrade coverage that seeds OrcaRouter prefix `orcarouter/` (strip off) and OpenCode Free prefixes `oc/` and `opencode/` (strip on).
- [ ] 2.3 Verify the migration sits on the current intended parent and preserves existing dashboard settings.

## 3. Settings module

- [ ] 3.1 Add both providers' fields to settings schemas, service data contracts, repository update paths, and API responses.
- [ ] 3.2 Encrypt, clear, and redact the OrcaRouter API key using the existing sidecar key-handling pattern. Treat OpenCode Free API key as optional.
- [ ] 3.3 Add both providers to cross-integration prefix and full-model uniqueness validation.
- [ ] 3.4 Add both providers to `SIDECAR_PROVIDER_ORDER` as `orcarouter` then `opencode` between OmniRoute and Ollama: `("claude", "openrouter", "orcarouter", "omniroute", "opencode", "ollama")`.
- [ ] 3.5 Add settings API and service tests for round-trip, redaction, optional OpenCode key, validation, default prefixes, and route conflicts including OmniRoute `oc/` vs OpenCode Free `oc/`.

## 4. OrcaRouter client and dispatch

- [ ] 4.1 Add `app/core/clients/orcarouter_sidecar.py` with config, errors, cached `/models`, chat, and streaming chat. Send Bearer auth when a key is present plus `HTTP-Referer` / `X-Title` / `User-Agent` identifying codex-lb.
- [ ] 4.2 Add `app/modules/proxy/orcarouter_sidecar_dispatch.py` cloning OpenRouter: config load, routing entry, payload (effort override, DeepSeek V4 repair), reservation settlement, request logs (`source="orcarouter_sidecar"`), cost-null without pricing.
- [ ] 4.3 Add unit tests for headers, cache, streaming, upstream errors, strip-off `orcarouter/auto`, full-model win over OpenRouter `openai/`, reservation release, and request-log fields.

## 5. OpenCode Free client and dispatch

- [ ] 5.1 Add `app/core/clients/opencode_sidecar.py` with the same HTTP surface as OpenRouter. Omit `Authorization` when the key is empty. Default base URL `https://opencode.ai/zen/v1`.
- [ ] 5.2 Add `app/modules/proxy/opencode_sidecar_dispatch.py`: strip-on `oc/` and `opencode/`, keyless dispatch, effort override, DeepSeek V4 repair, request logs (`source="opencode_sidecar"`), free-model zero cost for `-free` and `oc/big-pickle`.
- [ ] 5.3 Add unit tests for keyless headers, prefix strip, DeepSeek V4 reinjection, free-cost handling, streaming, upstream errors, and disabled fallthrough.

## 6. Unified routing and catalog

- [ ] 6.1 Wire both providers into `/v1/chat/completions` after API-key model validation and before native Codex account selection. Do not add `/v1/responses` dispatch.
- [ ] 6.2 Advertise configured full models only on `/v1/models` with `owned_by: "orcarouter"` and `owned_by: "opencode"`.
- [ ] 6.3 Add routing and catalog tests for enabled/disabled, discovered-only exclusion, API-key allowlists, and effective vs wire model.

## 7. Dashboard APIs

- [ ] 7.1 Add `app/modules/orcarouter_sidecar/` status, test-connection, and models APIs. Missing OrcaRouter key MUST skip the network and report missing-key status.
- [ ] 7.2 Add `app/modules/opencode_sidecar/` status, test-connection, and models APIs. Enabled OpenCode Free MUST test and list models without a key.
- [ ] 7.3 Register routers in `main.py` and add dashboard API tests for disabled, missing-key (OrcaRouter only), keyless success (OpenCode Free), unauthorized, and unreachable.

## 8. Accounts, request logs, and pricing

- [ ] 8.1 Add synthetic account summaries labeled `OrcaRouter` and `OpenCode Free`. OpenCode Free MUST appear when enabled even with no key.
- [ ] 8.2 Map request-log sources to those labels with transport `HTTP` and no sidecar badge.
- [ ] 8.3 Confirm OpenCode Free free-model cost behavior and OrcaRouter null-cost-without-pricing. Add regression tests.

## 9. Frontend schemas, API calls, and hooks

- [ ] 9.1 Add settings fields, including `orcarouterSidecarDefaultReasoningEffort` and OpenCode Free equivalent, to zod schemas and every `BASE_SETTINGS` fixture.
- [ ] 9.2 Add dashboard API calls and hooks `useOrcaRouterSidecar` / `useOpenCodeSidecar`.
- [ ] 9.3 Add MSW handlers and factory defaults.
- [ ] 9.4 Add frontend schema and payload tests.

## 10. Settings integration tabs

- [ ] 10.1 Add `OrcaRouterSidecarSettings` with `bare?: boolean`, API key, enable toggle above the callout, prefixes, full models, discovered models, timeouts, effort override, and test-connection.
- [ ] 10.2 Add `OpenCodeSidecarSettings` with `bare?: boolean`. Do not require an API key. Enable toggle above the callout. Same prefix/full-model/discovery/effort/test controls.
- [ ] 10.3 Add both IDs to `SidecarIntegrationCard` names and conflict-value collection.
- [ ] 10.4 Add exactly one OrcaRouter entry and one OpenCode Free entry to the existing `tabs` array in `sidecar-integrations.tsx`.
- [ ] 10.5 Add frontend tests for both tabs, default active tab when only that integration is enabled, persistence, discovered model add, OmniRoute `oc/` conflict, and OpenCode Free test without a key.

## 11. Backend verification

- [ ] 11.1 Run `openspec validate add-orcarouter-and-opencode-sidecar-routing --strict`.
- [ ] 11.2 Run targeted backend unit and integration tests for settings, routing, catalog, dispatch, dashboard APIs, request logs, and migrations.
- [ ] 11.3 Run backend linting for changed app and test files.

## 12. Frontend verification

- [ ] 12.1 Run targeted Settings Vitest suites from `frontend/`.
- [ ] 12.2 Run frontend typecheck / `bun run build` as required by schema fixture completeness.

## 13. Manual UI checks

- [ ] 13.1 Perform manual UI checks only if the user asks for manual verification and confirms it is safe to run the needed servers.
