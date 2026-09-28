## Context

`resolve_versioned_model_id` already keeps Opus 5.5 off the `*claude-opus-5*` glob, and the wire path already preserves any versioned id that starts with `claude-`. Sonnet 5.5 has the same shape: `*claude-sonnet-5*` matches `claude-sonnet-5-5`, `claude-sonnet-5.5`, and `cc/claude-sonnet-5-5`. Sonnet 5.5 is not in the versioned resolver, so `_resolve_sidecar_wire_model_and_effort` falls through and forwards `claude-sonnet-5`.

Stored full models include `claude-opus-5-5`, with prefix `cc/` strip enabled. A bare `claude-sonnet-5-5` does not match that prefix, so it stays off the sidecar until it is pinned as a full model. `cc/claude-sonnet-5-5` already matches the prefix and is the path that currently collapses.

Published Sonnet 5.5 rates for the fields this table stores match Sonnet 5: $2 input, $0.20 cache read, $10 output per 1M tokens. Context is 1M and max output is 128k. Cache writes ($2.50 for 5 minutes) are not stored. `ModelPrice` has no cache-write field.

CLIProxyAPI on this host does not list `claude-sonnet-5-5` yet. The catalog row is unmerged upstream (`router-for-me/models` #70). Pinning the id advertises it before that catalog can serve it. That is the same risk the Opus 5.5 pin accepted, and the wire-model fix has to land before the catalog does or the first successful catalog refresh still forwards Sonnet 5.

Native sidecar request-log cost for CLIProxyAPI still comes from the external catalog. The static row is the native price table and the identity used when a supplied table has no version entry. It must not replace a catalog price or an authoritative billed amount.

## Goals / Non-Goals

**Goals:**

- Forward Sonnet 5.5 as `claude-sonnet-5-5`
- Resolve that identity at $2 / $0.20 / $10
- Raise Cursor's 4096 `max_tokens` to the 32,768 floor, capped at 128,000, inside the 1,000,000 context window
- Pin the id on the stored full-model list without reordering existing entries
- Keep Sonnet 5, Opus 5.5, and Fable 5.1 behavior unchanged

**Non-Goals:**

- Haiku 5.5
- A new pricing glob `*claude-sonnet-5-5*`
- A cache-write column
- Restarting the running service
- Upgrading CLIProxyAPI or editing its config
- Replacing CLIProxyAPI catalog prices with the static table

## Decisions

1. Add `_SONNET_5_5_ID` beside the Opus 5.5 regex. Match the bare id or a routed prefix (`cc/`, `cp-`, `cp_`) anchored at the start. Do not treat every `-`, `_`, `:`, or `/` as a boundary, and do not add `*claude-sonnet-5-5*` to `DEFAULT_MODEL_ALIASES`. The family glob stays for real Sonnet 5 ids, including date stamps.
2. The wire path already keeps a versioned `claude-` id, strips a reasoning suffix, and retains a trailing `-YYYYMMDD` stamp. Dotted `5.5` normalizes to `claude-sonnet-5-5`. No second special case in the profile.
3. Static rates are input $2, cache-hit $0.20, output $10 per 1M tokens, the same stored fields as Sonnet 5. The resolved key is `claude-sonnet-5-5`. Cache writes are not stored.
4. Output bounds match the published 1M context and 128k max output, with the same 32,768 floor used for Sonnet 5. Sonnet 5 stays on its existing row.
5. One-shot migration appends `claude-sonnet-5-5` when absent, in id batches of 250. Case-insensitive presence, invalid JSON, and non-list values are left unchanged. Rows this upgrade actually appends are recorded in `claude_sonnet_5_5_pin_ownership`. Downgrade removes the id only from those rows, then drops the ownership table. A pin that was already stored stays. This is not re-applied on later settings saves, so an operator can remove the pin afterward. Settings saves keep the ownership table honest: a save that removes the pin keeps the row marked as processed, so a replayed upgrade does not re-add it, and a save that adds the pin back deletes the row's ownership entry, so downgrade leaves the operator's pin. The Opus 5.5 pin uses the same rules on its own table. One settings save updates both tables.

## Risks / Trade-offs

- This revision parents `20260925_010000_add_api_key_rate_limit_payment_required` and is the single head on this branch. A parallel migration on that parent creates a second Alembic head.
- A pinned full model is advertised even while CLIProxyAPI's catalog omits the id. Requests to it fail upstream until that catalog includes `claude-sonnet-5-5`.
- Lookalikes such as `claude-sonnet-5-50` still match `*claude-sonnet-5*` and price as Sonnet 5. They must not resolve as Sonnet 5.5.
- Historical request logs have no `claude-sonnet-5-5` rows, so there is no cost backfill.
- Stopping the collapse onto Sonnet 5 drops the Sonnet 5 output floor unless `claude-sonnet-5-5` has its own bounds row. The bounds row is part of this change.

## Migration Plan

Upgrade appends the full-model id. Downgrade removes it. The running process keeps the old code until restart, so the pin and the wire-model fix land together. Do not edit the live database before that restart.

## Open Questions

None.
