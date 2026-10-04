## Purpose

Calculated list prices for external integrations charged every cached input token at the full input rate. This change charges cached input at the cache-read rate the catalog publishes, and corrects the costs already stored.

## How it was found

The request log showed a `cc/claude-opus-5-5` request with 436.65K tokens, 435.94K of them cached, costing `$1.75`. At OpenRouter's published `$4 / $0.20 / $20` per 1M (input, cache read, output), that request costs about `$0.10`.

Across one deployment's last 30 days, Claude through CLIProxyAPI recorded about seven times its actual list price. Native Codex costs were already right: they use the static table, which has always carried cache-read rates.

## Rates

The migration's snapshot is the OpenRouter pricing reference's Claude cards, retrieved 2026-10-03. Per 1M tokens, input / cache read / output:

- `anthropic/claude-opus-5.5`: `4 / 0.20 / 20`
- `anthropic/claude-opus-5`, `anthropic/claude-opus-4.8`, `anthropic/claude-opus-4.7`, `anthropic/claude-opus-4.6`, `anthropic/claude-opus-4.5`: `5 / 0.50 / 25`
- `anthropic/claude-fable-5.1`: `10 / 0.25 / 50`
- `anthropic/claude-fable-5`: `10 / 1.00 / 50`
- `anthropic/claude-sonnet-5.5`, `anthropic/claude-sonnet-5`: `2 / 0.20 / 10`
- `anthropic/claude-sonnet-4.6`, `anthropic/claude-sonnet-4.5`, `anthropic/claude-sonnet-4`: `3 / 0.30 / 15`
- `anthropic/claude-haiku-4.5`: `1 / 0.10 / 5`
- `anthropic/claude-opus-4.1`: `15 / 1.50 / 75`

A request with 100,000 input tokens, 90,000 of them cached, and 1,000 output tokens on Opus 5.5 was recorded as `$0.42` and now costs `$0.078`.

## Ops

- Startup runs the migration. Its log line reports seeded records, repriced rows, corrected buckets, and records left without a dated card.
- Run `codex-lb model-prices refresh` once after deploying. Records the snapshot did not seed then read their catalog's cache-read rate. This changes future costs only.
- Request-log retention pauses until the hourly repair clears `upgrade_repair_from`.
- Cache writes are not recorded, so they still cost the input rate.
