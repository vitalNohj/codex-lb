# Send xAI Responses requests to CLIProxyAPI's native /v1/responses

## Why

xAI runs behind CLIProxyAPI with subscription (OAuth) logins. Today codex-lb converts every CLIProxyAPI `/v1/responses` request to a chat completion before sending it. For xAI this conversion loses things that matter:

- Chat has no field for `reasoning.encrypted_content`, so each earlier reasoning item is dropped. After the first reasoning turn, the prompt xAI receives no longer starts with the prefix it cached, so every later turn of a long conversation is billed in full.
- Responses-only fields are dropped or rewritten. `instructions` becomes a developer message and `reasoning.summary` disappears. An operator default reasoning effort replaces the effort the client chose.
- xAI's exact per-request cost (`usage.cost_in_usd_ticks`) and its reasoning-token count are never recorded.

CLIProxyAPI v8 accepts `/v1/responses` itself. For an xAI model it hands the body to its xAI executor, which posts it to xAI `/v1/responses` with only a few edits. The verification lab ran a real CLIProxyAPI binary with a fake xAI upstream: encrypted reasoning arrived byte-for-byte, and one `prompt_cache_key` reached xAI as both the cache key and `x-grok-conv-id`.

That native route has two hazards. CLIProxyAPI silently drops `previous_response_id`, and it falls back to a cache key derived from the opening messages when none is sent. It also relies on `routing.session-affinity` for any request codex-lb does not pin.

## What Changes

- **Native route for xAI only.** When `CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED` is on (default), `/v1/responses` traffic for a plain xAI model goes to CLIProxyAPI's native endpoint:
  - "Plain xAI model" means the routed CLIProxyAPI wire id has no `/` and starts with `grok`.
  - The body is forwarded with three edits: `model`, `prompt_cache_key`, and an operator default effort used only when the client sent none.
  - The response, streamed or not, goes back unchanged.
  - Every other CLIProxyAPI model, and every other provider, keeps the chat bridge. Prefixed ids such as `devin/grok-4-6` name a different CLIProxyAPI executor, so they keep it too.
  - Turning the setting off returns xAI to the bridge.
- **No key, no request.** When the CLIProxyAPI API key is missing, cleared or cannot be decrypted, the native route answers 503 `cliproxy_not_configured`. It builds and sends nothing, releases the reservation and logs the refusal, the same way OpenRouter and OrcaRouter handle a missing key.
- **Stateful fields stay rejected.** `previous_response_id`, `conversation` and `store: true` return a 400 before any quota is reserved, the same as on the bridge.
- **The cache key is always sent.** `prompt_cache_key` is the identity codex-lb pins the conversation on: the client key, a session header, or the derived key. A request with no identity gets a fresh random key, so CLIProxyAPI never falls back to its message-derived key. Such a request is not pinned.
- **Same routing and limits as the chat route.** The native route reuses the chat route's handling for each of these:
  - account selection, sticky pins and cooldown waits;
  - rebind on 401/403/429;
  - API-key service-tier enforcement and the usage reservation;
  - request logging.
- **Usage and cost.** Cached and reasoning token counts come from the Responses `usage` object. xAI's `cost_in_usd_ticks` (1 USD = 10^10 ticks) is recorded as the upstream-billed request cost, for streaming and non-streaming requests. The reservation settles on that cost.
- **Failures.** A non-2xx from CLIProxyAPI maps like the chat route's errors and releases the reservation. A `response.failed` or `error` event, or a stream that ends without a terminal event, is logged as an error:
  - If the turn reported usage, it is charged, because xAI billed those tokens.
  - Otherwise the reservation is released.

  A stream that ends early also gets a terminal `response.failed` frame.
- **Session affinity guard.** Each CLIProxyAPI quota poll reads `routing.session-affinity`:
  - The state is published as `codex_lb_cliproxy_session_affinity_enabled`.
  - A warning is logged when affinity is off, and repeated hourly while it stays off.
  - The dashboard toggle shows a warning when affinity is off.
  - codex-lb does not switch affinity back on; the toggle is the operator's.
- **Observability.** `codex_lb_cliproxy_xai_responses_route_total{route}` counts xAI Responses requests by route (`native` or `bridge`).

## Out of scope

- `/v1/responses/compact` for xAI; it keeps its current path.
- A native codex-lb xAI provider.

## Capabilities

### Modified capabilities

- `responses-api-compat`
- `sticky-session-operations`

## Impact

- Backend: `app/modules/proxy/cliproxy_responses_dispatch.py` (new), `app/modules/proxy/api.py`, `app/modules/proxy/claude_sidecar_dispatch.py`, `app/modules/proxy/cliproxy_account_routing.py`, `app/modules/proxy/external_pricing_logging.py`, `app/modules/proxy/responses_chat_bridge.py`, `app/core/clients/claude_sidecar.py`, `app/modules/claude_sidecar/session_affinity_guard.py` (new), `app/modules/claude_sidecar/quota_poller.py`, `app/modules/claude_sidecar/service.py`, `app/core/metrics/prometheus.py`, `app/core/config/settings.py`.
- Frontend: the session-affinity toggle warns when affinity is off.
- One new setting, `CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED`. It is a rollback switch: if CLIProxyAPI's native xAI path misbehaves, an operator can put xAI back on the bridge with one environment change, without a release. No migrations.
