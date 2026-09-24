## Overview

A pool lives one layer above `resolve_sidecar_route`. The resolver stays a
single-owner, deterministic function; cross-provider uniqueness of prefixes and
full models stays enforced; every target is still dispatched through its own
provider path with that provider's pricing, effort override, Cursor
compatibility, and DeepSeek repair. The only new machinery is: resolve an alias
to N candidates, pick the next healthy one, open the upstream, and if the open
fails in a retryable way, try the next.

This is why the "star a sidecar as the default owner for a bare model id" idea
was rejected: it would relax full-model uniqueness (the invariant that makes the
resolver unambiguous and the save-time conflict error meaningful) and it still
would not say what happens when the starred owner fails. Ordering inside the
pool *is* the star.

## Locked names

| Surface | Value |
| --- | --- |
| Settings JSON column (existing) | `model_aliases_json` |
| Stored value shape | `{ "<alias>": { "targets": ["<model>", ...] } }` |
| Settings API field | `model_aliases: dict[str, ModelAliasPoolSchema]` |
| Frontend field | `modelAliases: Record<string, { targets: string[] }>` |
| Request-log columns (new) | `upstream_model` (String, nullable), `pool_attempts` (Integer, nullable) |
| Request-log `model` | the alias the client sent (unchanged semantics) |
| Health endpoint | `GET /api/settings/alias-pools/health` |
| Client-visible error when every target fails | last attempt's client-facing error, plus header `X-Codex-LB-Pool-Attempts: <n>` |
| Log line | `alias_pool_attempt request_id=… alias=… target=… attempt=… outcome=served\|failover\|rejected\|skipped_cooling` |

`pooled/` is **not** a reserved prefix and is never matched by the resolver.
It is a naming convention for operators. An alias named `pooled/glm-5.3` is
just an alias whose id happens to contain a slash, exactly like `or-foo/bar`.

## Data model

```json
{
  "glm-5.3": { "targets": ["orcarouter/z-ai/glm-5.3", "or-z-ai/glm-5.3", "cc/glm-5.3"] },
  "custom_r1": { "targets": ["cc/claude-opus-4-8"] }
}
```

- `targets` is ordered; index 0 is preferred.
- A strategy field is deliberately absent. Ordered failover is the only
  behavior this change ships. If round-robin is ever wanted it becomes a
  sibling key (`"strategy": "round_robin"`) and the loader defaults it to
  `"failover"` for existing rows. Round-robin across paid routers is wrong for
  coding sessions anyway: a stable primary keeps prompt-cache hits and
  consistent behavior; the fallback exists for failure, not for spreading.
- `parse_model_aliases` accepts both `{alias: str}` and
  `{alias: {"targets": [...]}}` for one release so a replica on the previous
  version can still read a row written by this one (the old reader ignores
  non-string values, so the alias simply stops resolving on that replica
  rather than crashing it). The Alembic data migration rewrites strings to
  one-element pools; downgrade rewrites one-element pools back to strings and
  keeps only `targets[0]` for larger pools.

### Save-time validation (`SettingsService`)

Reject with a `ValueError` that surfaces as `422` and the existing settings
error envelope:

1. Empty `targets`.
2. Duplicate target within a pool (case-insensitive).
3. A target that is itself a configured alias (no chains, therefore no cycles).
4. A pool with **two or more** targets where any target resolves to a provider
   that is not pool-capable, or to the native Codex path. Native Codex has its
   own account failover and is not an HTTP sidecar; mixing it into a pool would
   need the Responses bridge to expose an open/stream split, which is out of
   scope.
5. Length caps as today: alias and each target 256 characters or fewer; at most
   16 targets per pool.

A **one-target** pool is allowed to point anywhere an alias can point today,
including native Codex, so the migration cannot invalidate an existing alias.

Reconcile `custom_alias_catalog` against the alias key set exactly as now.

## Resolution

`resolve_model_alias(model, aliases) -> tuple[str, ...]`:

- Unaliased model or `None` aliases: `(model,)`.
- Alias: the tuple of targets in order.

`resolve_request_model_alias` keeps its name and returns the tuple. The
Responses hooks take `[0]`; `v1_chat_completions` takes the whole tuple. The
info log `model_alias_resolved` gains `targets=<n>`.

## Dispatch loop

New module `app/modules/proxy/alias_pool_dispatch.py`:

```python
async def dispatch_chat_with_failover(
    request, payload, *, alias: str, targets: tuple[str, ...], api_key,
    reservation, rate_limit_headers, settings, routing_entries, configs,
    cursor_compat,
) -> Response
```

Per attempt:

1. Skip targets in cooldown. If **every** target is cooling, attempt the one
   whose cooldown expires soonest (do not return 503 for a cooldown alone).
2. `payload.model = target`; `decision = resolve_sidecar_route(target, routing_entries)`.
   A key with an enforced model never pools (the enforced model replaces the
   alias), so the target is exactly the model dispatched.
3. Access is settled before the loop and before the reservation.
   `authorize_pool_targets` runs `validate_model_access(api_key, target,
   routing_entries=...)` for every target - the provider and canonical model
   that target routes to, which is what the loop sends - after the existing
   check on the alias id. A target the key may not use is dropped from the
   pool; if no target is allowed the last rejection is returned as a 403 with
   no reservation held, the same order as the single-provider path. This
   keeps "a restricted key cannot reach a disallowed target through an alias"
   true per target, and the loop only accepts the resulting `AuthorizedPool`.
4. `opened = await provider.open_chat(...)`. This performs the upstream POST
   and returns either an `OpenedStream` (status 200, body not yet read), a
   `NonStreamResult` (full JSON body), or raises the provider's error types.
5. Classify:
   - `OpenedStream` / `NonStreamResult`: build the response as today, log
     `outcome=served`, return. Streaming iterators take the already-open
     stream instead of opening one.
   - Retryable failure (see table): record cooldown, log `outcome=failover`,
     continue.
   - Non-retryable failure: log `outcome=rejected`, return the provider's
     client-facing error as today (including the Cursor context-length
     synthetic success, which must keep winning over failover).
6. After the last target fails, return the **last** attempt's client-facing
   error with `X-Codex-LB-Pool-Attempts`.

Reservation and limits: `_enforce_request_limits` runs **once** against the
alias before the loop. Each provider's settlement/release path is unchanged and
runs for the attempt that served. Failed-over attempts never settle (they
produced no usage); the reservation is carried to the next attempt. If every
attempt fails, the last attempt's error path releases it exactly as the single
provider path does today.

`latency_queue_ms` on the log row accumulates the time spent in failed-over
attempts, matching the field's existing definition ("failed failover attempts")
on the Codex path.

### Retryable classification

| Signal | Retryable | Cooldown |
| --- | --- | --- |
| Transport error, DNS failure, connect/read timeout (`*SidecarUnavailableError`) | yes | 60 s |
| 401, 403 (upstream credential/pool failure, already remapped to 503 for clients) | yes | 60 s |
| 402 | yes | 30 min |
| 408 | yes | 60 s |
| 429 | yes | `Retry-After` seconds if present and at most 1 h, else 60 s |
| 500, 502, 503, 504, 520-526 | yes | 60 s |
| 400, 404, 413, 422, any other 4xx | no | none |
| Cursor context-length error on a cursor-compat request | no (synthetic success) | none |
| Upstream 200 whose stream later fails | no (this change) | none |

The provider's one-shot retry (`retry-orcarouter-provider-failure`) runs
**inside** an attempt, before the loop classifies it: an open that fails with
HTTP status 500 or above (transport included) is sent once more to the same
target, and only a second failure reaches the table above. So
402/429/401/403/408 fail over at once, a 5xx costs the target two calls first,
and `pool_attempts` counts targets, not calls. A stream that opened with 200
and then fails before its first chunk is reopened on the same target under
that same single retry, but it never fails over: the client status is already
committed. The retry stays
per target because OrcaRouter and OpenRouter pick the upstream provider
themselves, and a second call to the preferred target is how a pool keeps its
stated order. The worst case is a 524 (~300 s) paid twice before the next
target is tried, the same cost the single-target path already accepts.

Cooldowns are process-local and keyed by the **target string**, not the
provider, so `orcarouter/z-ai/glm-5.3` cooling down does not stop
`orcarouter/auto`. A multi-replica deployment learns the cooldown per replica;
that is acceptable because the cost is one wasted upstream round-trip per
replica per cooldown window.

### Open-before-commit split

Each pool-capable dispatcher gains:

```python
async def open_chat(client, body) -> OpenedChat   # POST, raise on >=400, do not read body
async def stream_opened(opened, ...) -> AsyncIterator[bytes]   # existing iterator, minus the open
```

The three clients already raise `_error_from_status` before yielding inside
`stream_chat_completion`, so the split is mechanical: the `async with` enters in
`open_chat`, the `AsyncExitStack` that owns it is handed to the iterator, and
the iterator closes it on completion or client disconnect. Keepalive injection
and the Cursor usage fallback wrap the iterator as before. The single-target
(legacy alias or unaliased) path uses the same split so there is one code path.

Non-streaming requests already surface upstream errors before any response is
built, so they need no split.

### Providers out of scope for pools

`claude` (CLIProxyAPI) has a large dispatcher with its own account-exclusion
retry loop, quota polling, and Anthropic-shaped image conversion; `nvidia`,
`ollama`, `opencode_go`, `omniroute` have not been split. They remain valid as
single targets and are rejected as members of a 2+ pool with a message naming
the target and the provider. Adding them later is: implement `open_chat`, add
the provider key to `POOL_CAPABLE_PROVIDERS`.

## Catalog

`build_discoverable_alias_model_entries` receives the pool. Entry metadata is
cloned from the first target that is present in `existing_entries`; if none is
present, the sidecar default fields are used. The alias is listed when **any**
target is visible for the API key. `custom_alias_catalog` overlays apply
unchanged.

## Dashboard

- Routing settings: alias row shows an ordered chip list of targets with
  add (datalist of known model ids), remove, and move up/down. Existing
  one-target rows render the same component.
- Each chip shows health from `GET /api/settings/alias-pools/health`:
  `healthy`, `cooling (until HH:MM, last: 402 payment_required)`. Polled while
  the Routing panel is open, 15 s.
- `/api/settings/alias-pools/health` is dashboard-authenticated and returns
  `{ "<alias>": { "<target>": { "state": "healthy"|"cooling", "until": iso|null, "last_status": int|null, "last_error": str|null } } }`.
- Save uses the whole `modelAliases` map as today.
- Screenshots required in the PR (PRINCIPLES P5).

## Failure modes

- Every target cooling: try the soonest-to-expire one; if it fails again its
  cooldown is refreshed. The client sees the real upstream error, never a
  cooldown-only 503.
- Settings saved while a request is mid-loop: the loop holds the tuple it
  resolved at the start; the next request sees the new pool.
- Alias deleted: `custom_alias_catalog` row and cooldown entries are dropped.
- Operator lists a target on a provider that is later disabled: the target
  resolves to no route or a disabled route and is treated as a non-retryable
  rejection for that target, the loop continues; save-time validation does not
  re-run on integration toggles, so this is logged at `warning` once per
  alias per minute.
- Client disconnects between attempts: the loop checks
  `await request.is_disconnected()` before each open and stops.

## Testing

- Unit: pool parsing (both shapes), validation rules 1-5, retryable
  classification table, cooldown expiry and soonest-to-expire selection,
  catalog entry building with partially visible targets.
- Integration (fake upstreams, real handler): 402 on target 1 then 200 on
  target 2 for streaming and non-streaming; 400 on target 1 is returned, target
  2 never called; Cursor context-length on target 1 returns the synthetic
  success; restricted key allowed on alias but not target 1 skips to target 2;
  all targets fail returns last error with the attempts header; request log
  row has `model=alias`, `upstream_model=target2`, `pool_attempts=2`.
- Migration: string aliases become one-element pools; downgrade truncates to
  `targets[0]`.
- Frontend: reorder, add, remove targets; health chip states.
