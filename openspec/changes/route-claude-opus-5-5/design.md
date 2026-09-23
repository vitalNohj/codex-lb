## Context

`resolve_versioned_model_id` already keeps Fable 5.1 off the `*claude-fable-5*` glob. Opus 5.5 has the same shape: `*claude-opus-5*` matches `claude-opus-5-5`, `claude-opus-5.5`, and `cc/claude-opus-5-5`. `canonical_sidecar_model` consults the versioned resolver first, but `_resolve_sidecar_wire_model_and_effort` only preserves a versioned id when it is exactly `claude-fable-5-1`. Every other versioned Claude id falls through to the family alias and is rewritten.

CLIProxyAPI's `/v1/models` list on this host already includes `claude-opus-5-5`. It does not include Sonnet 5.5 or Haiku 5.5. Stored full models are `claude-opus-5` and `claude-fable-5-1`, with prefix `cc/` strip enabled. A bare `claude-opus-5-5` does not match that prefix, so it stays off the sidecar until it is pinned as a full model. `cc/claude-opus-5-5` already matches the prefix and is the path that currently collapses.

Native sidecar request-log cost for CLIProxyAPI still comes from the external catalog. The static row is the native price table and the identity used when a supplied table has no version entry. It must not replace a catalog price or an authoritative billed amount.

## Goals / Non-Goals

**Goals:**

- Forward Opus 5.5 as `claude-opus-5-5`
- Price that identity at $4 / $0.20 / $20
- Raise Cursor's 4096 `max_tokens` to the 32,768 floor, capped at 128,000, inside the 1,000,000 context window
- Pin the id on the stored full-model list without reordering existing entries
- Keep Opus 5, Fable 5, and Fable 5.1 behavior unchanged

**Non-Goals:**

- Sonnet 5.5 or Haiku 5.5
- GPT-6 Sol or Luna (separate pricing change)
- A cache-write column, or a fast-mode tier on Claude rows
- Restarting the running service
- Replacing CLIProxyAPI catalog prices with the static table

## Decisions

1. Add `_OPUS_5_5_ID` beside the Fable 5.1 regex. Match the bare id or a routed prefix (`cc/`, `cp-`, `cp_`) anchored at the start. Do not treat every `-`, `_`, `:`, or `/` as a boundary, and do not add `*claude-opus-5-5*` to `DEFAULT_MODEL_ALIASES`. The family glob stays for real Opus 5 ids, including date stamps.
2. Treat every versioned id that starts with `claude-` the way Fable 5.1 is treated: strip a reasoning suffix, keep a trailing `-YYYYMMDD` stamp, otherwise forward the canonical hyphen id. Dotted `5.5` normalizes to `claude-opus-5-5`.
3. Static rates are input $4, cache-hit $0.20, output $20 per 1M tokens. Cache writes ($5 for 5 minutes, $8 for 1 hour) and fast mode ($8 / $40) are not stored. `ModelPrice` has no cache-write field, and existing Claude rows have no fast tier.
4. Output bounds match the published 1M context and 128k max output, with the same 32,768 floor used for Fable 5.1. Opus 5 stays unbounded, which is the current behavior.
5. One-shot migration appends `claude-opus-5-5` when absent, in id batches of 250. Case-insensitive presence, invalid JSON, and non-list values are left unchanged. Rows this upgrade actually appends are recorded in `claude_opus_5_5_pin_ownership`. Downgrade removes the id only from those rows, then drops the ownership table. A pin that was already stored stays. This is not re-applied on later settings saves, so an operator can remove the pin afterward.

## Risks / Trade-offs

- Parallel migrations that also parent `20260919_000000_add_openai_compat_endpoints` create a second Alembic head when both land. This revision is the single head on this branch.
- A pinned full model is advertised even if CLIProxyAPI later drops the id. The current CLIProxyAPI catalog includes it.
- Lookalikes such as `claude-opus-5-50` still match `*claude-opus-5*` and price as Opus 5. They must not resolve as Opus 5.5.
- Historical request logs have no `claude-opus-5-5` rows, so there is no cost backfill.

## Migration Plan

Upgrade appends the full-model id. Downgrade removes it. The running process keeps the old code until restart, so the pin and the wire-model fix land together. Do not edit the live database before that restart.

## Open Questions

None.
