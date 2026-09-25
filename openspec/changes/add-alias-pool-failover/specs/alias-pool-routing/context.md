# Alias pool routing

Requirements live in [spec.md](spec.md). This document explains why the pool
sits where it does and what to look at when it misbehaves.

## Purpose and scope

An operator buys GLM 5.3 from OrcaRouter (cheap, prepaid) and also has it
available on OpenRouter and through a coding plan behind CLIProxyAPI. Cursor is
configured with one model name. When OrcaRouter's balance hits zero the
session should keep working without anyone editing client configuration.

Scope: `POST /v1/chat/completions`, ordered failover, before-first-byte only,
three providers. Non-goals: round-robin or weighted spreading, mid-stream
failover, native Codex accounts inside a pool, Responses-path pooling.

## Why the alias layer

Aliases already resolve before `resolve_sidecar_route`, so a pool is "resolve
to N names, try each". Every target is dispatched through its own provider
path, so per-provider pricing, effort overrides, Cursor compatibility, and
DeepSeek repair are inherited for free, and cost attribution stays correct per
real provider. The resolver's single-owner invariant (full-model and prefix
uniqueness across sidecars) is untouched.

### Alternative considered: starred default owner

Allow the same bare model id in several sidecars and let the operator "star"
one as the default. Rejected because it relaxes the uniqueness invariant that
makes the resolver deterministic and the save-time conflict error meaningful,
adds a second precedence mechanism next to aliases, hides catalog entries, and
still does not define what happens when the starred owner fails. Prefixes
already namespace the same model per sidecar; the pool alias is the bare name.

### Alternative considered: do it in CLIProxyAPI

CLIProxyAPI pools credentials for the same alias across `openai-compatibility`
blocks with `fill-first` and per-block `priority`. It works as a stopgap when
codex-lb routes `glm-5.3 -> cc/glm-5.3`, but it loses OrcaRouter's billed-cost
telemetry, splits configuration across two tools, and 402 is not in its
default retry set (needs `request-scoped-errors`).

## Why before-first-byte only

Once `200 text/event-stream` has been committed, switching upstreams would mean
either replaying partial output (duplicated text) or silently dropping it.
Both routers sometimes smuggle an error inside a 200 stream; handling that
needs a buffer-until-first-delta hold, which is a later change. The open/stream
split introduced here is the prerequisite for it.

## Retryable set rationale

- 402 is the motivating case (OrcaRouter out of credit). 30 minutes because a
  top-up is a human action.
- 401/403 are already remapped to a client 503 by `sidecar_upstream_errors.py`
  because they are never the client's fault once codex-lb accepted the key.
- 429 honors `Retry-After` when present; capped at one hour so a misbehaving
  header cannot park a target for a day.
- 400/413/422 would fail on every target (bad request, oversized prompt) and
  the Cursor context-length synthetic success depends on seeing the 400.
- 404 usually means the model id is wrong on that provider, which is a
  configuration error the operator should see, not paper over.

## Example

Settings:

```json
{
  "model_aliases": {
    "pooled/glm-5.3": {
      "targets": ["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3"]
    }
  }
}
```

Request `POST /v1/chat/completions {"model": "pooled/glm-5.3", "stream": true, ...}`:

1. Access check on `pooled/glm-5.3`; reservation taken against it.
2. Attempt 1: `orcarouter/z-ai/glm-5.3` -> resolver says `orcarouter`, wire
   model `orcarouter/z-ai/glm-5.3` (prefix not stripped). POST returns 402.
   Cooldown 30 min. Log `alias_pool_attempt ... attempt=1 outcome=failover`.
3. Attempt 2: `or-z-ai/glm-5.3` -> resolver says `openrouter`, wire model
   `z-ai/glm-5.3` (prefix stripped). POST returns 200. Stream handed to the
   OpenRouter iterator. Log `attempt=2 outcome=served`.
4. Request log: `model=pooled/glm-5.3`, `upstream_model=or-z-ai/glm-5.3`,
   `pool_attempts=2`, `cost_usd` from OpenRouter usage.

For the next 30 minutes attempt 1 is `outcome=skipped_cooling` and OpenRouter
is tried first.

## Operational notes

- Health: Routing settings chips, or `GET /api/settings/alias-pools/health`.
- Logs: grep `alias_pool_attempt` by `request_id`.
- Cooldowns are per process. After a restart every target is healthy.
- A pool whose targets all live on one provider (two OpenRouter model ids) is
  valid and useful for "try the `:free` variant first".
- Adding a provider to pools: implement `open_chat` for its dispatcher, add
  its key to `POOL_CAPABLE_PROVIDERS`, extend the classification tests.

## Related

- `chat-completions-compat` (alias access gating, dispatch)
- `model-catalog-compat` (alias entries on `/v1/models`)
- `api-keys` (allowlist semantics on alias vs target)
- `external-model-pricing` (per-provider settlement is unchanged)
