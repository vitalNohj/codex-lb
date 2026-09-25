## Why

Dashboard model aliases map one client-facing name to exactly one real model
(`{alias: target}`). Operators who buy the same model from several places
(OrcaRouter, OpenRouter, a CLIProxyAPI-fronted coding plan) cannot express
"prefer this one, use the other when it fails". When OrcaRouter runs out of
credit, a Cursor or Codex session pointed at `orcarouter/z-ai/glm-5.3` gets a
402 and stops; the operator has to notice, edit the client config, and restart
the session. codex-lb already knows about the other providers and already
resolves aliases before sidecar routing, so it is the right place to fail over.

## What Changes

- Model aliases become **alias pools**: each alias resolves to an ordered list of
  one or more target model ids instead of a single string. A one-target pool
  behaves exactly like today's alias. Pool aliases are ordinary alias names;
  `pooled/glm-5.3` is a convention, not a reserved prefix.
- On `POST /v1/chat/completions`, a pool is tried in order. An attempt that
  fails **before any byte has been sent to the client** with a retryable upstream
  failure (transport error, timeout, 402, 408, 429, 5xx, or an upstream 401/403)
  is retried on the next target. Non-retryable failures (400, 404, 413, 422 and
  anything else) are returned as today. The first attempt that produces a
  response is the response; there is no mid-stream failover in this change.
- Streaming dispatch on the poolable providers opens the upstream connection
  **before** the `200 text/event-stream` response is committed, so an upstream
  4xx/5xx can still be failed over. Today the connection is opened lazily inside
  the streaming iterator, after Starlette has already committed the status.
- A target that fails with a retryable failure enters an **in-memory cooldown**
  (402: 30 minutes, 429: `Retry-After` or 60 seconds, other: 60 seconds). Cooled
  targets are skipped; when every target is cooling, the one whose cooldown
  expires soonest is tried so recovery is automatic.
- Request logs for pool requests record the alias as `model` (what API-key
  allowlists, limits, and reservations key on) and the serving target in a new
  `upstream_model` column, plus `pool_attempts`.
- The settings API accepts and returns `model_aliases` as
  `{alias: {"targets": [..]}}`. The legacy `{alias: "target"}` shape is
  accepted on write and normalized. Save validation rejects targets that are
  themselves aliases, duplicate targets, empty pools, and, for pools with two or
  more targets, targets on providers that are not yet pool-capable.
- `GET /v1/models` advertises a pool alias as one entry, cloning the metadata of
  the first visible target. The alias is hidden only when **no** target is
  visible for the requesting API key.
- Dashboard Routing settings gain a target list per alias row (add, remove,
  reorder) and a per-target health chip (healthy, cooling until, last error).
- Pool-capable providers in this change: `orcarouter`, `openrouter`, and
  `openai_compat:{uuid}`. Other providers may be a pool's **single** target
  (legacy alias behavior) and may be added to pools in later changes once their
  dispatch is split into open/stream phases.

## Impact

- Affected specs: `chat-completions-compat`, `model-catalog-compat`, `api-keys`,
  `database-migrations`, `frontend-architecture`, new capability
  `alias-pool-routing`.
- Affected code: `app/modules/proxy/model_aliasing.py` (pool resolution),
  new `app/modules/proxy/alias_pool_dispatch.py` (attempt loop, retryable
  classification, cooldown), `app/modules/proxy/api.py` (`v1_chat_completions`
  and the Responses alias hook), `app/modules/proxy/{orcarouter,openrouter,openai_compat}_*dispatch.py`
  (open-before-commit split), `app/modules/settings/{schemas,service,repository}.py`,
  `app/db/models.py`, one Alembic revision, `frontend/src/features/settings/**`.
- Database: `request_logs.upstream_model` (String, nullable) and
  `request_logs.pool_attempts` (Integer, nullable). `dashboard_settings.model_aliases_json`
  keeps its column and its `{alias: str}` values; only an alias with fallback
  targets is stored as `{alias: {"targets": [str, ...]}}`. Keeping single
  aliases as strings lets a replica on the previous release read, and keep
  across its own settings saves, every pre-upgrade alias during a rolling
  upgrade.
- No new `CODEX_LB_*` setting and no new required setup step (PRINCIPLES P1/P2).
  A deployment with no pools behaves byte-for-byte as before.
- `/v1/responses` is unchanged: a pool alias on the Responses path resolves to
  its first target only. Responses dispatch today only serves OmniRoute and
  OpenCode Go, neither of which is pool-capable.
