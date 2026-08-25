## Why

Operators already reach OrcaRouter and OpenCode Free through OmniRoute, which hides auth, model identity, and failures behind one hop. They want those two providers as first-class External Integrations so codex-lb owns routing, API-key allowlists, request logs, and Settings tabs without depending on OmniRoute executors for this traffic.

OrcaRouter is an OpenAI-compatible paid gateway (`https://api.orcarouter.ai/v1`, `sk-orca-` keys). OpenCode Free is a keyless OpenAI-compatible endpoint (`https://opencode.ai/zen/v1`). Both fit the existing sidecar contract. Other OmniRoute providers (MiMoCode, DeepSeek Web) stay out of scope.

## What Changes

- Add dashboard-managed OrcaRouter sidecar configuration: enable toggle, base URL, encrypted API key, model prefixes, full models, timeouts, cache TTL, health fields, and operator reasoning-effort override.
- Add dashboard-managed OpenCode Free sidecar configuration with the same shape except API key is optional/absent; enabled + reachable is enough to mark it configured.
- Add outbound OpenAI-compatible HTTP clients for both providers (`/models` and `/chat/completions`, streaming and non-streaming).
- Add both providers to the unified sidecar resolver and `POST /v1/chat/completions` dispatch. Seed OrcaRouter with prefix `orcarouter/` (strip off) and OpenCode Free with prefixes `oc/` and `opencode/` (strip on). Do not seed vendor prefixes such as `openai/` for OrcaRouter.
- Advertise only configured full models from each enabled integration on `GET /v1/models`.
- Surface each as a read-only synthetic account and as a tab in the existing Settings "External Integrations" card. Request-log labels are `OrcaRouter` and `OpenCode Free` with transport `HTTP`.
- Apply existing DeepSeek V4 `reasoning_content` repair on both chat-completions paths. Treat OpenCode Free models as zero-cost when they match the existing free-model rules (`-free` suffix or opaque allowlist).

## Non-goals

- Do not add MiMoCode, DeepSeek Web, OpenCode Zen paid, or OpenCode Go.
- Do not route these providers through OmniRoute/CLIProxyAPI/OpenRouter dispatch.
- Do not hook either provider into `/v1/responses` in this change.
- Do not port OmniRoute combo stacks, fingerprint/proxy rotation, or Playwright/PoW web executors.
- Do not seed OrcaRouter with OpenRouter-colliding vendor prefixes (`openai/`, `google/`, `anthropic/`, `deepseek/`). Pinned OrcaRouter models are operator-configured full models.
- Do not manage OrcaRouter or OpenCode process lifecycle.
- Do not add quota pollers, usage queues, or per-account pause controls.

## Capabilities

### New Capabilities

None. Follow the Ollama sidecar precedent: management APIs and UI live under the modified capabilities below.

### Modified Capabilities

- `chat-completions-compat`: unified-resolver routing, OpenAI-compat relay, streaming, effort override, DeepSeek V4 repair, and error handling for OrcaRouter and OpenCode Free.
- `model-catalog-compat`: configured full-model entries for both integrations on OpenAI-compatible `/v1/models`.
- `frontend-architecture`: OrcaRouter and OpenCode Free tabs in the existing External Integrations card.
- `api-keys`: API-key model enforcement and allowlist checks use the effective client model for both integrations.
- `database-migrations`: dashboard settings schema for both sidecar configurations.
- `proxy-runtime-observability`: request logs, usage/cost rules, and synthetic account presentation for both integrations.

## Impact

- Backend settings persistence and one Alembic migration for both providers' columns.
- New clients `app/core/clients/orcarouter_sidecar.py` and `app/core/clients/opencode_sidecar.py`.
- New dispatch modules and dashboard modules mirroring OpenRouter/Ollama.
- Sidecar resolver provider order and `/v1/chat/completions` switch in `app/modules/proxy/api.py`.
- Accounts, request-log labels, pricing free-model handling, and DeepSeek V4 hook list.
- Frontend Settings schemas, fixtures, two tab components, hooks, and Request Logs labels.
- Unit and integration tests for settings uniqueness, routing, catalog, dispatch, dashboard APIs, and frontend tabs.
