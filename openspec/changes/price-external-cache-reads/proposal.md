## Why

The external price store kept only a catalog's input and output rate. Every cached input token was charged the full input rate, even when the catalog publishes a cache-read rate of a tenth or less. Claude traffic served through CLIProxyAPI is almost all cache reads, so its calculated list price was inflated about fivefold to fourteenfold. One `cc/claude-opus-5-5` request with 436,322 input tokens, 435,940 of them cached, recorded `$1.75` instead of about `$0.10`.

The bug began on 2026-09-02 with persistent external pricing. On one deployment it inflated the 30-day API cost card about fourfold and turned a real increase of about 140% into `+892%`.

The rule was deliberate: the spec required full-rate cached input because "not every catalog publishes a cache-read rate". OpenRouter publishes one for every Claude model, and the parser read that field and then dropped it.

## What Changes

- Store the cache-read rate each catalog publishes (`external_model_prices.cached_input_per_1m`) and charge cached input at it. Use the full input rate only when the catalog publishes none.
- Treat a cache-read rate published in an unreadable shape as unparseable, the same as an unreadable input or output rate, so a parse failure never inflates cost or erases a stored rate.
- Make the maintenance refresh compare, apply, and report cache-read rates.
- One Alembic upgrade adds the column. It seeds the rate for records priced from the OpenRouter reference, using a dated 2026-10-03 snapshot of its Claude cards. It reprices the request logs that provably carry the full-rate figure and moves every rollup that folded them by the same delta.
- Pause request-log retention while a post-upgrade rollup repair is pending, so the repair never loses rows it must refold.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `external-model-pricing`: cached input uses the published cache-read rate, unreadable cache-read rates are unparseable, refresh tracks cache-read rates, and a one-time correction of historical full-rate costs.
- `data-retention`: request-log pruning is skipped while `upgrade_repair_from` is set.

## Impact

- Code: `app/core/usage/external_pricing/catalogs.py`, `app/core/usage/external_pricing/store.py`, `app/core/usage/external_pricing/maintenance.py`, `app/db/models.py`, `app/core/retention/job.py`
- DB: new nullable column, a cost correction for request logs and usage rollups, and a no-op cost downgrade
- Tests: catalog parsing, request path, maintenance, end-to-end Claude sidecar cost, retention, and migration tests
- Docs: `docs/model-pricing.md`, and the `external-model-pricing` and `data-retention` specs and context
- No API or frontend changes. The dashboard already renders the stored costs and totals.
