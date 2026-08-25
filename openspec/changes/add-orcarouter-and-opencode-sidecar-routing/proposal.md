## Why

Operators already reach OrcaRouter, OpenCode Zen, and OpenCode Free through OmniRoute. They want those three as first-class External Integrations so codex-lb owns routing, API-key allowlists, request logs, and Settings tabs without depending on OmniRoute for this traffic.

OrcaRouter is an OpenAI-compatible gateway (`https://api.orcarouter.ai/v1`, `sk-orca-` keys). OpenCode Zen is the authenticated OpenAI-compatible gateway (`https://opencode.ai/zen/v1`, Zen API key). OpenCode Free is the same zen URL with no Authorization header. All three fit the existing OpenRouter HTTP sidecar contract. Do not use the Ollama SDK adapter.

## What Changes

- Add dashboard-managed sidecar configuration for three providers: OrcaRouter, OpenCode Zen, and OpenCode Free. Each gets enable toggle, base URL, prefixes, full models, timeouts, cache TTL, health fields, and operator reasoning-effort override.
- OrcaRouter and OpenCode Zen encrypt an API key at rest. OpenCode Free does not require a key; enabled + reachable is enough to mark it configured.
- Add outbound OpenAI-compatible HTTP clients for all three (`GET /models`, `POST /chat/completions`, streaming and non-streaming).
- Add all three to the unified sidecar resolver and `POST /v1/chat/completions` dispatch. Seed prefixes:
  - OrcaRouter: `orcarouter/` strip **off**
  - OpenCode Zen: `opencode-zen/` strip **on**
  - OpenCode Free: `oc/` strip **on**
- Do not seed vendor prefixes such as `openai/` on OrcaRouter. Do not seed `opencode/` on OpenCode Free (that prefix belongs to official Zen config format; Cursor through OmniRoute already uses `opencode-zen/`).
- Advertise only configured full models from each enabled integration on `GET /v1/models`.
- Surface each as a read-only synthetic account and as a tab in the existing Settings "External Integrations" card. Request-log labels are `OrcaRouter`, `OpenCode Zen`, and `OpenCode Free` with transport `HTTP`.
- Apply existing DeepSeek V4 `reasoning_content` repair on all three chat-completions paths. Treat `-free` models and opaque ids (`big-pickle`, `oc/big-pickle`, `opencode-zen/big-pickle`) as zero-cost.

## Non-goals

- Do not add MiMoCode, DeepSeek Web, OpenCode Go, or other OmniRoute web/session executors.
- Do not route these providers through OmniRoute/CLIProxyAPI/OpenRouter dispatch.
- Do not hook these providers into `/v1/responses` or Zen `/messages` in this change (GPT/Claude on Zen stay out).
- Do not port OmniRoute combo stacks, fingerprint/proxy rotation, or Playwright/PoW web executors.
- Do not seed OrcaRouter with OpenRouter-colliding vendor prefixes (`openai/`, `google/`, `anthropic/`, `deepseek/`). Pinned OrcaRouter models are operator-configured full models.
- Do not manage OrcaRouter or OpenCode process lifecycle. Do not disable or uninstall OmniRoute in this change.
- Do not add quota pollers, usage queues, or per-account pause controls.

## Capabilities

### New Capabilities

None. Follow the Ollama sidecar precedent: management APIs and UI live under the modified capabilities below.

### Modified Capabilities

- `chat-completions-compat`: unified-resolver routing, OpenAI-compat relay, streaming, effort override, DeepSeek V4 repair, and error handling for OrcaRouter, OpenCode Zen, and OpenCode Free.
- `model-catalog-compat`: configured full-model entries for all three integrations on OpenAI-compatible `/v1/models`.
- `frontend-architecture`: OrcaRouter, OpenCode Zen, and OpenCode Free tabs in the existing External Integrations card.
- `api-keys`: API-key model enforcement and allowlist checks use the effective client model for all three integrations.
- `database-migrations`: dashboard settings schema for all three sidecar configurations.
- `proxy-runtime-observability`: request logs, usage/cost rules, and synthetic account presentation for all three integrations.

## Impact

- Backend settings persistence and one Alembic migration for all three providers' columns.
- New clients `app/core/clients/orcarouter_sidecar.py`, `app/core/clients/opencode_zen_sidecar.py`, and `app/core/clients/opencode_sidecar.py`.
- New dispatch modules and dashboard modules mirroring OpenRouter (not Ollama).
- Sidecar resolver provider order and `/v1/chat/completions` switch in `app/modules/proxy/api.py`.
- Accounts, request-log labels, pricing free-model handling, and DeepSeek V4 hook list.
- Frontend Settings schemas, fixtures, three tab components, hooks, and Request Logs labels.
- Unit and integration tests for settings uniqueness, routing, catalog, dispatch, dashboard APIs, and frontend tabs.
- Implementer execution checklist: `openspec/changes/add-orcarouter-and-opencode-sidecar-routing/plan.md`.
