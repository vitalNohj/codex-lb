## Purpose

Fill Request Logs `--` cost for GPT-6 Astra. Cost is OpenAI list price from token usage, same as GPT-5.6 Sol.

## Non-goals

- Catalog/OpenRouter auto-pricing for native Codex traffic
- Restarting the live service from this change
- Cache-write or Batch-tier pricing

## Example

Live store before this change:

- `gpt-6-astra` rows inserted while an uncommitted price row was in memory: `cost_usd` set, `cost_source = static_table`
- `gpt-6-astra` rows after the 2026-09-09 02:26 UTC restart: `cost_usd` NULL

After: `add_log` for `gpt-6-astra` with 200k input + 1M output stores `$52.00` (2 + 50). Cached tokens use the 10% cache-hit rate. Requests over 272k input tokens use the long-context rates. Folded usage rollups gain those dollars via a cost-only delta; the fold watermark stays put.

## Related

- OpenAI GPT-6 Astra list price: $10 input / $1 cached input / $50 output per 1M; Fast doubles; Flex halves; long-context (>272K input) is $20 / $2 / $75
