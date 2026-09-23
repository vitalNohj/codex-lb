## Purpose

Route and price Claude Opus 5.5 on the CLIProxyAPI sidecar without sending it to Opus 5.

## What shipped

Confirmed 2026-09-23 against Anthropic and the local CLIProxyAPI catalog:

- Claude Opus 5.5 is released. API id `claude-opus-5-5`. List price $4 input, $0.20 cache read, $20 output per 1M tokens. Context 1M, max output 128k. CLIProxyAPI `/v1/models` already lists `claude-opus-5-5`.
- Claude Sonnet 5.5 and Claude Haiku 5.5 are not released. They are not in this change.
- GPT-6 Sol and GPT-6 Luna are native Codex models. Their pricing is a separate change. There is no GPT-6 Terra.

## Why the wire id collapses

`DEFAULT_MODEL_ALIASES` maps `*claude-opus-5*` to `claude-opus-5`. That glob matches `claude-opus-5-5`. On current main, `apply_sidecar_model_profile("claude-opus-5-5")` returns `claude-opus-5`, and `get_pricing_for_model` returns the $5 / $0.50 / $25 row.

The production sidecar prefix is `cc/` with strip enabled. `cc/claude-opus-5-5` already routes to CLIProxyAPI, then the profile rewrites the forwarded model. Bare `claude-opus-5-5` does not match `cc/`, so the upgrade also pins it next to `claude-opus-5` and `claude-fable-5-1`.

## Decisions

- Versioned identity, not a longer glob. A glob would price lookalikes such as `claude-opus-5-50`.
- Cache-write rates ($5 for 5 minutes, $8 for 1 hour) and fast mode ($8 / $40) are not stored. The price table has no cache-write field, and Claude rows have no fast tier.
- External catalog prices and billed amounts stay authoritative for CLIProxyAPI request logs. The static row is the native identity and the fallback when a supplied table has no version entry.
- No historical backfill. Request logs have no Opus 5.5 rows.

## Example

A client request for `cc/claude-opus-5-5` with `max_tokens` 4096 forwards `model` `claude-opus-5-5` and `max_tokens` 32768. `cc/claude-opus-5` still forwards `claude-opus-5` with the client's 4096 left unchanged.

## Ops

The running `codex-lb.service` does not load this code or migration until restart. Do not restart it until the operator confirms in-flight work can drop.
