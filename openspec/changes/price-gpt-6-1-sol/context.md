## Purpose

Native request logs for `gpt-6.1-sol` show no dollar cost because the static price table has no row for it. This change prices it the same way GPT-6 Sol is priced and fills in its history.

## Rates

Published OpenAI API list prices, fetched 2026-10-03 from developers.openai.com/api/docs/pricing. Per 1M tokens, input / cached input / output:

- Standard `2 / 0.10 / 10`
- Fast/priority `4 / 0.20 / 20`
- Flex `1 / 0.05 / 5`
- Standard long context, above 272,000 input tokens: `4 / 0.20 / 15`

Cache writes (`$2.50` standard) are published and not stored. `ModelPrice` has no cache-write field, and request logs do not record cache-write tokens.

OpenAI also publishes a Fast long-context rate (`8 / 0.40 / 30`). `_effective_rates` applies Fast rates without a long-context step for every model, so a Fast request above 272,000 input tokens is priced at the short Fast rates. This predates the change and applies to GPT-6 Astra and GPT-6 Sol too.

## Example

200,000 input tokens (100,000 of them cached) and 1,000,000 output tokens at Standard:

- 100,000 uncached × `$2` + 100,000 cached × `$0.10` + 1,000,000 output × `$10`, per 1M
- `$0.20 + $0.01 + $10.00 = $10.21`

GPT-6 Sol charges `$10.22` for the same request, because its cache read is `$0.20`.

## Backfill

The migration prices a row only when its `cost_usd` is NULL and nothing else settled its price. It then moves each rollup that already counted the row:

- The lifetime account and API-key totals, for rows up to `folded_through`.
- Hourly and demand buckets the surviving raw rows can rebuild, by arming `upgrade_repair_from`.
- The hour that starts before the earliest surviving row, directly. Retention pruned part of it, so the repair never rebuilds it.

## Non-goals

Subscription Codex traffic still spends plan quota. The stored `cost_usd` is the published API list price, the same estimate GPT-6 Sol already shows. Sidecar routing is unchanged.

## Ops

New inserts stay NULL until the process restarts onto this code. Historical NULL rows fill when startup runs the Alembic upgrade. The post-upgrade repair then refolds buckets from the armed marker, and request-log pruning waits for it (`data-retention`). Do not restart the shared service until the operator says in-flight work can stop. `downgrade()` does not clear costs.
