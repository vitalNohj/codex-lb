## Context

Haiku 5.5 is the first Haiku priced by prompt length. Anthropic's pricing page (checked 2026-10-07) lists, per 1M tokens:

| Prompt length | Input | Cache read | 5m write | 1h write | Output |
| --- | --- | --- | --- | --- | --- |
| <= 100,000 | $0.10 | $0.01 | $0.125 | $0.20 | $0.50 |
| > 100,000 | $0.50 | $0.05 | $0.625 | $1.00 | $2.50 |

`ModelPrice` already supports this shape through `long_context_threshold_tokens` and the `long_context_*` rates, and `_effective_rates` switches the whole request, output included, when total input (cached included) exceeds the threshold.

The id `claude-haiku-5-5` matches no family glob, so the sidecar already forwards it unchanged. Only bounds, pricing, and the pin are missing.

## Goals / Non-Goals

**Goals:**

- Price both tiers for native cost accounting
- Raise small `max_tokens` to the 32,768 floor, capped at 128,000, inside 1,000,000 context
- Pin the id on the stored full-model list without reordering existing entries
- Fix the Sonnet 5.5 cache-hit rate

**Non-Goals:**

- Cache-write rates or the Batch API discount (no `ModelPrice` field)
- Tiered rates in the external catalog path. CLIProxyAPI request-log cost comes from OpenRouter, whose `overrides` block the catalog parser does not read yet, so prompts over 100,000 tokens would log at the lower rate there. Not planned: Haiku 5.5 clients are capped below 100,000 prompt tokens, so only the short-prompt rates apply in practice.
- Restarting the service or changing CLIProxyAPI

## Decisions

1. Use the existing long-context fields, threshold 100,000. A prompt of exactly 100,000 tokens uses the short-prompt rates.
2. Cached tokens count toward the threshold. Anthropic does not say otherwise, and this matches how the other tiered models in the table are priced.
3. No introductory or limited-time rate is recorded. None is published for Haiku 5.5; the only introductory note on the pricing page is the expired Sonnet 5 one. A code comment says to recheck if one appears.
4. The pin migration follows the Opus 5.5 and Sonnet 5.5 pins: append when absent, record ownership, downgrade removes only owned rows, settings saves keep ownership honest.

## Risks / Trade-offs

- The pinned id is advertised before CLIProxyAPI on a host refreshes its catalog. Requests fail upstream with `unknown provider` until it does.
- The new tokenizer counts about 30% more tokens than Haiku 4.5 for the same text, so cost comparisons with 4.5 understate the difference.

## Migration Plan

Upgrade appends the id; downgrade removes it from owned rows and drops the ownership table. Single Alembic head, parent `20261005_000000_add_full_model_stars`.

## Open Questions

None.
