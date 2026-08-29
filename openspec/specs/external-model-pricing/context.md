# external-model-pricing context

Narrative background for operators and maintainers. Normative requirements live
in [spec.md](./spec.md); this page explains why the design looks the way it does
and how to run it.

## Why this exists

Request-log cost used to come from a hand-maintained static price table matched
by substring glob. That table is not a catalog subset: it uses a different id
convention, so most catalog ids missed exact match and fell through to a pattern
like `*claude-opus-4*`.

Measured against the live public catalogs, those globs resolved 92 real model ids
and priced 48 of them wrong, by up to 13.3x. Concrete cases:

| incoming id | glob picked | catalog rate | table rate | error |
| --- | --- | --- | --- | --- |
| `anthropic/claude-opus-4.5` | `claude-opus-4` | $5 / $25 | $15 / $75 | 3x |
| `cohere/command-r7b-12-2024` | `cohere/command-r` | $0.037 / $0.15 | $0.50 / $1.50 | 13.3x |
| `aion-labs/aion-rp-llama-3.1-8b` | `llama-3.1-8b` | $0.80 / $1.60 | $0.10 / $0.10 | 0.13x |
| `openai/gpt-4o-mini-tts` | `openai/gpt-4o-mini` | $0.60 / $12.00 | $0.15 / $0.60 | 0.25x |

Two spellings of one model (`claude-opus-4.5` and `claude-opus-4-5`) produced a
3x different cost on otherwise identical requests. The visible symptom was a
missing cost, but the larger problem was a confident wrong number that looked
exactly like a billed figure.

So this capability does two separable things: it resolves prices from
authoritative catalogs with abstention, and it separates a billed amount from a
calculated one so the two can never be confused again.

## Layout

| Module | Job |
| --- | --- |
| `app/core/usage/external_pricing/resolution.py` | Pure incoming-id to catalog-id mapping. No I/O. |
| `app/core/usage/external_pricing/catalogs.py` | Catalog sources and their parsing. |
| `app/core/usage/external_pricing/store.py` | Durable records, rates, provenance, backoff. |
| `app/core/usage/external_pricing/service.py` | Cache-first request path, deduplicated lookup. |
| `app/core/usage/external_pricing/maintenance.py` | One explicit refresh pass. |
| `app/modules/proxy/external_pricing_sources.py` | Per-integration catalog and routing wiring. |
| `app/modules/proxy/external_pricing_logging.py` | Cost fields for one request log row. |

`external_model_prices` is the single owner of pricing records and resolution
state. Each row is keyed on `(provider, incoming_model)` where `incoming_model`
is the id exactly as the request carried it, prefix included, so the request
path is one indexed read.

## Source precedence

Resolution stops at the first hit:

1. **Explicit operator alias.** Exact key match on the dashboard alias map. The
   operator said what the id means, so nothing overrides it.
2. **Configured routing prefix.** A prefix is removed only when the operator
   marked it `strip`, longest match first, mirroring `resolve_sidecar_route`. The
   remainder re-enters resolution. This is what maps `cc/claude-fable-5` to the
   Anthropic entry instead of trimming `cc/` and hoping.
3. **Exact catalog id**, case-folded.
4. **Punctuation-normalized id** (`.` and `_` folded to `-`), unique match only.
   Zero within-catalog collisions were observed across 577 live ids.
5. **Vendor-qualified bare name**, unique match only.

Catalogs are consulted in authority order: the serving provider's own catalog
first, then OpenRouter as the broad pricing reference. This matters because 37 of
the 98 ids listed by both OrcaRouter and OpenRouter are priced differently, by up
to 1.97x. Each step runs across every catalog before the next weaker step starts,
so a precise match in the fallback beats a fuzzy match in the preferred source.

CLIProxyAPI contributes **no** price catalog: it publishes model ids with no
rates. Contributing an unpriced catalog would make every id look "listed but not
token priced" and stop the search before the vendor's real catalog is consulted.
It contributes only its prefixes and the alias map.

## Abstention

Any step that finds more than one plausible candidate abstains and records
`ambiguous`. This is not caution: the live cross-vendor collisions differ by
1.33x to 2.8x, so guessing is wrong most of the time it matters.

Variant suffixes (`:free`, `:batch`) never fall back to a base entry. Those
variants are billed at different rates - `:batch` at 50% - so inheriting the base
price would substitute a wrong number for a missing one.

## Actual versus calculated cost

`request_logs.cost_source` records where `cost_usd` came from:

| value | meaning |
| --- | --- |
| `upstream_billed` | The serving integration reported debiting this amount. Authoritative actual spend. |
| `catalog_calculated` | Published token rates times recorded usage. Deterministic arithmetic over an authoritative rate, but list price rather than the actual debit. |
| `operator_configured` | A model source's own configured rates. |
| `static_table` | The legacy built-in table, still used by non-participating paths. |
| NULL | Unknown provenance. Rows written before the column existed. Treat as unknown, never as billed. |

A billed amount always wins and is stored verbatim. It folds in tiered pricing,
peak multipliers, cache ratios, and minimum-quota rounding that are not
reproducible client-side, so a calculated figure never overwrites it and a billed
figure is never recomputed against list pricing.

Calculated costs are exact arithmetic, not estimates, and are included in cost
totals. The provenance is preserved because list price may still differ from the
actual debit.

`request_logs.price_status` records the resolution outcome so the UI can tell a
model that *should* be priced from one that was never expected to be.

## UI markers

| Cost cell | When |
| --- | --- |
| `!!` + tooltip | A participating integration's model that should be token-priceable but is `unresolved` or `ambiguous`. |
| `--` | Ollama, OmniRoute, missing token usage, `not_token_priced`, and the main proxy path. |
| A figure with a list-price tooltip | `catalog_calculated`. |
| A plain figure | `upstream_billed` and everything else. |

## Negative cache and backoff

An unresolved or ambiguous record carries `attempt_count` and `next_retry_at`.
The schedule is 5m, 30m, 2h, 6h, then 24h, capped - so a permanently unknown id
settles at one lookup per day rather than one per request. A record that becomes
resolvable has its failure state cleared.

Resolved and not-token-priced records carry no retry deadline. They are settled
answers; only the maintenance command revisits them.

Concurrent first sightings of one id collapse onto a single in-flight job, so a
traffic burst to a newly routed model produces one catalog fetch.

## Maintenance command

```
codex-lb model-prices refresh
```

One pass, idempotent, unscheduled. It fetches each catalog once in bulk, updates
changed rates and provenance, and prints what it did:

```
External model price maintenance
- Records examined: 42
- Rates updated: 2
- Newly resolved: 1
- Unchanged: 38
- Preserved after a source failure: 0
- Still unresolved: 1
- Ambiguous: 0
```

It is deliberately not a poller. Prices change rarely, so an interval would spend
every tick re-confirming the same numbers, and an unattended refresh that swaps a
rate silently is harder to reason about than one whose output names every change.

Two failure modes are treated differently, and the distinction is the point:

* **Source unreachable** - the record keeps its prior rate. A timeout is not a
  delisting, and preserving a probably-correct rate beats replacing it with
  nothing.
* **Source reachable and no longer listing the model** - the record becomes
  unresolved. The source answered; continuing to report the old rate would serve
  a price no live listing backs.

## Operational notes

- **Cached input** is priced at the full input rate. No participating catalog
  publishes a cache-read rate for every model, and assuming a discount ratio
  would substitute an invented number for a published one.
- **Failure is always toward no price.** A store read failure, a catalog outage,
  or a resolver exception costs a cost figure, never the request.
- **Free models** record a real `$0.00`: zero is a published price.
- **Migrations are additive-nullable**, so rollback is a revert.

## What was rejected

- **Generalized web search or scraping.** Official pricing pages carry no
  machine-readable prices (Anthropic docs have zero `ld+json` blocks) or block
  non-browser clients outright (openai.com returns 403). A scraped price is also
  attacker-influenceable, and `cost_usd` feeds cost-based API-key quotas, which
  would make a poisoned number an enforcement input.
- **A curated alias map for the residue.** The known residue is a handful of
  genuine price conflicts. A stale curated entry is a silent multi-x error, which
  is worse than the abstention it would replace.
- **Persisting prices as a cache with a TTL poller.** See the maintenance section.
