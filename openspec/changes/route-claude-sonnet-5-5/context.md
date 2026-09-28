## Purpose

Route and price Claude Sonnet 5.5 on the CLIProxyAPI sidecar without sending it as Sonnet 5.

## What shipped

Confirmed 2026-09-28 against Anthropic's release notes:

- Claude Sonnet 5.5 is released. API id `claude-sonnet-5-5`. List price $2 input, $0.20 cache read, $10 output per 1M tokens. Context 1M, max output 128k. Adaptive thinking is on. `thinking.type: disabled` is rejected upstream.
- The local CLIProxyAPI catalog (7.3.15, refreshed from `router-for-me/models`) does not list `claude-sonnet-5-5`. The catalog addition is unmerged (`router-for-me/models` #70). This change does not wait on that merge, and it does not upgrade CLIProxyAPI.
- Claude Haiku 5.5 is not released.

## Why the wire id collapses

`DEFAULT_MODEL_ALIASES` maps `*claude-sonnet-5*` to `claude-sonnet-5`. That glob matches `claude-sonnet-5-5`. `apply_sidecar_model_profile("claude-sonnet-5-5")` returns `claude-sonnet-5`.

The production sidecar prefix is `cc/` with strip enabled. `cc/claude-sonnet-5-5` already routes to CLIProxyAPI, then the profile rewrites the forwarded model. Bare `claude-sonnet-5-5` does not match `cc/`, so the upgrade also pins it the way `claude-opus-5-5` is pinned.

## Decisions

- Versioned identity, not a longer glob. A glob would price lookalikes such as `claude-sonnet-5-50`.
- Stored rates match Sonnet 5. The distinct fact is the canonical id `claude-sonnet-5-5`.
- Cache-write rate ($2.50 for 5 minutes) is not stored. The price table has no cache-write field.
- External catalog prices and billed amounts stay authoritative for CLIProxyAPI request logs. The static row is the native identity and the fallback when a supplied table has no version entry.
- No historical backfill. Request logs have no Sonnet 5.5 rows.

## Example

A client request for `cc/claude-sonnet-5-5` with `max_tokens` 4096 forwards `model` `claude-sonnet-5-5` and `max_tokens` 32768. `cc/claude-sonnet-5` still forwards `claude-sonnet-5`.

## Ops

The running `codex-lb.service` does not load this code or migration until restart. Do not restart it until the operator confirms in-flight work can drop. A pinned id is advertised before CLIProxyAPI can serve it. Those requests fail upstream until the catalog includes `claude-sonnet-5-5`.
