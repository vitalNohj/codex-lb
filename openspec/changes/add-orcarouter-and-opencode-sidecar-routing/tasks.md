## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, design, tasks, delta specs, context, and implementer plan for OrcaRouter, OpenCode Zen, and OpenCode Free sidecar routing.
- [x] 1.2 Validate `add-orcarouter-and-opencode-sidecar-routing` with `openspec validate add-orcarouter-and-opencode-sidecar-routing --strict`.

## 2. Database settings

- [ ] 2.1 Add OrcaRouter, OpenCode Zen, and OpenCode Free sidecar columns to `DashboardSettings`, including enabled, base URL, encrypted API key, prefixes JSON, full models JSON, timeouts, cache TTL, health fields, and default reasoning effort.
- [ ] 2.2 Create one Alembic migration with upgrade and downgrade coverage that seeds OrcaRouter prefix `orcarouter/` (strip off), OpenCode Zen prefix `opencode-zen/` (strip on), and OpenCode Free prefix `oc/` (strip on). Parent the revision on the live Alembic head at implementation time.
- [ ] 2.3 Verify the migration sits on a single-head graph and preserves existing dashboard settings.

## 3. Settings module

- [ ] 3.1 Add all three providers' fields to settings schemas, service data contracts, repository update paths, and API responses.
- [ ] 3.2 Encrypt, clear, and redact the OrcaRouter and OpenCode Zen API keys using the existing sidecar key-handling pattern. Treat OpenCode Free API key as optional.
- [ ] 3.3 Add all three providers to cross-integration prefix and full-model uniqueness validation.
- [ ] 3.4 Add all three providers to `SIDECAR_PROVIDER_ORDER` as `("claude", "openrouter", "orcarouter", "opencode-zen", "omniroute", "opencode", "ollama")`.
- [ ] 3.5 Add settings API and service tests for round-trip, redaction, optional OpenCode Free key, required Zen/Orca keys, validation, default prefixes, and route conflicts including OmniRoute `oc/` vs OpenCode Free `oc/` and OmniRoute `orcarouter/` vs OrcaRouter `orcarouter/` and OmniRoute `opencode-zen/` vs OpenCode Zen `opencode-zen/`.

## 4. OrcaRouter client and dispatch

- [ ] 4.1 Add `app/core/clients/orcarouter_sidecar.py` by cloning `openrouter_sidecar.py`: config, errors, cached `/models`, chat, and streaming chat. Send Bearer auth when a key is present plus `HTTP-Referer` / `X-Title` / `User-Agent` identifying codex-lb. Default base URL `https://api.orcarouter.ai/v1`.
- [ ] 4.2 Add `app/modules/proxy/orcarouter_sidecar_dispatch.py` cloning OpenRouter: config load, routing entry, payload (effort override, DeepSeek V4 repair), reservation settlement, request logs (`source="orcarouter_sidecar"`), cost-null without pricing.
- [ ] 4.3 Add unit tests for headers, cache, streaming, upstream errors, strip-off `orcarouter/auto`, full-model win over OpenRouter `openai/`, reservation release, and request-log fields.

## 5. OpenCode Zen client and dispatch

- [ ] 5.1 Add `app/core/clients/opencode_zen_sidecar.py` cloning OpenRouter. Require Bearer when a key is stored. Default base URL `https://opencode.ai/zen/v1`. User-Agent `codex-lb/opencode-zen-sidecar`.
- [ ] 5.2 Add `app/modules/proxy/opencode_zen_sidecar_dispatch.py`: strip-on `opencode-zen/`, effort override, DeepSeek V4 repair, request logs (`source="opencode_zen_sidecar"`), free-model zero cost for `-free` and `opencode-zen/big-pickle`.
- [ ] 5.3 Add unit tests for headers, prefix strip `opencode-zen/mimo-v2.5-free` → `mimo-v2.5-free`, missing-key skip, DeepSeek V4 reinjection, streaming, upstream errors, and disabled fallthrough.

## 6. OpenCode Free client and dispatch

- [ ] 6.1 Add `app/core/clients/opencode_sidecar.py` with the same HTTP surface as OpenRouter. Omit `Authorization` when the key is empty. Default base URL `https://opencode.ai/zen/v1`. User-Agent `codex-lb/opencode-sidecar`.
- [ ] 6.2 Add `app/modules/proxy/opencode_sidecar_dispatch.py`: strip-on `oc/`, keyless dispatch, effort override, DeepSeek V4 repair, request logs (`source="opencode_sidecar"`), free-model zero cost for `-free` and `oc/big-pickle`.
- [ ] 6.3 Add unit tests for keyless headers, prefix strip, DeepSeek V4 reinjection, free-cost handling, streaming, upstream errors, and disabled fallthrough.

## 7. Unified routing and catalog

- [ ] 7.1 Wire all three providers into `/v1/chat/completions` after API-key model validation and before native Codex account selection. Do not add `/v1/responses` dispatch.
- [ ] 7.2 Advertise configured full models only on `/v1/models` with `owned_by: "orcarouter"`, `owned_by: "opencode-zen"`, and `owned_by: "opencode"`.
- [ ] 7.3 Add routing and catalog tests for enabled/disabled, discovered-only exclusion, API-key allowlists, and effective vs wire model.

## 8. Dashboard APIs

- [ ] 8.1 Add `app/modules/orcarouter_sidecar/` status, test-connection, and models APIs. Missing OrcaRouter key MUST skip the network and report missing-key status.
- [ ] 8.2 Add `app/modules/opencode_zen_sidecar/` status, test-connection, and models APIs. Missing Zen key MUST skip the network and report missing-key status.
- [ ] 8.3 Add `app/modules/opencode_sidecar/` status, test-connection, and models APIs. Enabled OpenCode Free MUST test and list models without a key.
- [ ] 8.4 Register routers in `main.py` and add dashboard API tests for disabled, missing-key (OrcaRouter and Zen), keyless success (OpenCode Free), unauthorized, and unreachable.

## 9. Accounts, request logs, and pricing

- [ ] 9.1 Add synthetic account summaries labeled `OrcaRouter`, `OpenCode Zen`, and `OpenCode Free`. OpenCode Free MUST appear when enabled even with no key. OrcaRouter and Zen MUST require a stored key to show as configured/active.
- [ ] 9.2 Map request-log sources to those labels with transport `HTTP` and no sidecar badge.
- [ ] 9.3 Extend `_OPAQUE_FREE_MODELS` with `opencode-zen/big-pickle`. Confirm `-free` detection covers `opencode-zen/mimo-v2.5-free`. Add regression tests.

## 10. Frontend schemas, API calls, and hooks

- [ ] 10.1 Add settings fields, including default reasoning effort for all three, to zod schemas and every `BASE_SETTINGS` fixture. Missing a `.default({})` field in fixtures breaks `bun run build`.
- [ ] 10.2 Add dashboard API calls and hooks `useOrcaRouterSidecar` / `useOpenCodeZenSidecar` / `useOpenCodeSidecar`.
- [ ] 10.3 Add MSW handlers and factory defaults.
- [ ] 10.4 Add frontend schema and payload tests.

## 11. Settings integration tabs

- [ ] 11.1 Add `OrcaRouterSidecarSettings` with `bare?: boolean`, API key, enable toggle above the callout, prefixes, full models, discovered models, timeouts, effort override, and test-connection.
- [ ] 11.2 Add `OpenCodeZenSidecarSettings` with the same shape as OpenRouter (API key required). Callout: create a key at https://opencode.ai/docs/zen/ ; prefix `opencode-zen/` strips on the wire.
- [ ] 11.3 Add `OpenCodeSidecarSettings` with `bare?: boolean`. Do not require an API key. Enable toggle above the callout. Same prefix/full-model/discovery/effort/test controls. Callout: keyless public zen endpoint; expect 429/503.
- [ ] 11.4 Add all three IDs to `SidecarIntegrationCard` names and conflict-value collection.
- [ ] 11.5 Add exactly one tab entry each to the existing `tabs` array in `sidecar-integrations.tsx`. Labels: `OrcaRouter`, `OpenCode Zen`, `OpenCode Free`.
- [ ] 11.6 Add frontend tests for all three tabs, default active tab when only that integration is enabled, persistence, discovered model add, OmniRoute prefix conflicts, OpenCode Free test without a key, and OpenCode Zen test requiring a key.

## 12. Backend verification

- [ ] 12.1 Run `openspec validate add-orcarouter-and-opencode-sidecar-routing --strict`.
- [ ] 12.2 Run targeted backend unit and integration tests for settings, routing, catalog, dispatch, dashboard APIs, request logs, and migrations.
- [ ] 12.3 Run backend linting for changed app and test files.

## 13. Frontend verification

- [ ] 13.1 Run targeted Settings Vitest suites from `frontend/` (not repo root).
- [ ] 13.2 Run frontend typecheck / `bun run build` as required by schema fixture completeness.

## 14. Manual UI checks

- [ ] 14.1 Perform manual UI checks only if the user asks for manual verification and confirms it is safe to restart or use the shared instance.
