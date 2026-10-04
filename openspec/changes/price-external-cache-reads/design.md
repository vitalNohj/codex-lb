## Context

`external_model_prices` held one input and one output rate per `(provider, incoming model)`. `parse_per_token_pricing` read OpenRouter's `input_cache_read` and then discarded it with `include_cached=False`. `catalog_from_published_models` did the same for OpenAI-compatible endpoints. `calculate_cost_from_usage` already supports a cache-read rate and falls back to the input rate when it is `None`, so every external cached token cost the full input rate.

The request path, cost totals, and rollups were all consistent with each other. The rule they implemented was wrong, which is why reviews against the spec found nothing.

## Goals / Non-Goals

**Goals:**

- Price cached input at the published cache-read rate, and at the input rate only when the catalog publishes none
- Never let a parse failure inflate a cost or erase a stored cache-read rate
- Correct the stored history: request logs, lifetime account and API-key rollups, and hourly and demand buckets, including buckets whose raw rows retention already pruned
- Keep every rollup equal to the rows it folds, so the existing readers need no change

**Non-Goals:**

- Cache-write pricing. Request logs record no cache-write tokens, so cache writes still cost the input rate. Anthropic bills them at 1.25x or 2x.
- Correcting rows priced from catalogs with no dated snapshot. A later `codex-lb model-prices refresh` fixes their future cost only.
- Pricing models that are still unresolved (`!!`) or logged with no cost
- Adjusting `api_key_limits.current_value` for cost limits. That counter restarts at each window reset.

## Decisions

- **Store the rate, do not derive it.** A nullable `cached_input_per_1m` column is threaded through every store writer, `PriceRecord`, and the `ModelPrice` used by the request path. NULL means the catalog published no cache-read rate, and the existing fallback to the input rate applies. A discount ratio was rejected: it would invent a number the catalog did not publish.
- **Unreadable is not absent.** `_catalog_entry` marks an entry unparseable when its cache-read field is present but unreadable, or when any parsed rate is non-finite. Absent, `null`, empty, and negative values remain "none published". Without this, one schema change upstream would make refresh replace a stored `$0.20` rate with nothing and inflate cache-heavy costs again. Unparseable entries already keep the stored price and retry.
- **Refresh compares all three rates.** `_rates_changed` includes the cache-read rate, and the report line names it (`cached=0.2` or `cached=none published`). Otherwise records stored before this change would read as unchanged and never get a cache-read rate.
- **Seed history from a dated snapshot, not from the static table.** Seeding from `get_pricing_for_model` was tested and rejected. It misses `cc/claude-fable-5.1` (797 rows), and it maps OpenRouter `:free` ids to the static `free` entry. The migration instead freezes the 15 OpenRouter Claude cards published on 2026-10-03, as exact strings, and converts them with the runtime parser's arithmetic. A record gets a seeded rate only if it is resolved, its source is `openrouter:reference`, and its stored input and output equal the card exactly. A seeded rate is therefore bit-identical to what a refresh would store. The snapshot never prices a request.
- **Reprice only on proof.** A row is repriced only if all of these hold: its `cost_source` is `catalog_calculated`, its cost is non-NULL, it has cached tokens, it has output tokens, and its record was seeded. It must also store exactly the full-rate figure (relative tolerance 1e-9) or already the published figure. The second case makes a rerun a no-op. Any other stored value means something else priced it, and it is left alone.
- **Lifetime rollups take exact deltas.** These are the template's rules from `20260922_000000_backfill_gpt_6_sol_luna_costs`. API-key deltas cover every folded non-warmup row, soft-deleted rows included. Account deltas cover only the `max(id)` row of each `(account_id, request_id, requested_at)` group, and not soft-deleted rows.
- **Refold what raw rows cover, patch what they cannot.** Arming `upgrade_repair_from` makes the existing repair rebuild hourly and demand buckets from raw rows, from `ceil_hour(earliest surviving row)`. Retention already pruned the rows below that floor, so those buckets are corrected arithmetically. An hourly bucket is corrected only if all of these hold:
  - It is integration traffic with no account.
  - Its model has one unambiguous rate across all providers.
  - Every request is priced on the recorded output count, except failed or cancelled requests (`request_count - cost_count <= error_count + cancelled_count`). Those are logged without tokens, and an unpriced request that carried tokens would break the full-rate equality anyway.
  - No surviving row in it failed the row proof.
  - Its stored total equals the full-rate figure.

  Demand slots have no `cost_count`, so a slot is proven only inside a clean hour. The pruned part of a corrected hourly bucket also moves the API-key lifetime total. Every other bucket moves by exactly its surviving rows' deltas. Account buckets are never rewritten from sums, because the account dedupe rule cannot be replayed for rows that no longer exist.
- **Pause retention during the repair.** `_prune_request_logs` returns early while `upgrade_repair_from` is set. Pruning during the repair would delete rows the repair has not refolded yet, and those buckets would keep pre-repair figures. Capping the cutoff at the marker does not work, because deleting the oldest rows moves the repair's start past the marker.
- **Alembic revision files cannot use dataclasses.** Alembic loads revision modules outside `sys.modules`, and `dataclasses` with string annotations then fails (`AttributeError: 'NoneType' object has no attribute '__dict__'`). The migration's value types are `NamedTuple`s and a plain class.
- **Downgrade drops the column and keeps the corrected costs.** Nothing records the pre-upgrade figures, and they were wrong. Rollups stay consistent with their rows, and rerunning the upgrade changes nothing.

## Risks / Trade-offs

- [Published rates can change] → The snapshot only repairs history, and only for records whose stored card matches it exactly. Future costs follow the stored record, which `codex-lb model-prices refresh` updates.
- [The correction is a list price, not an invoice] → Same as every `catalog_calculated` cost. Cache writes are still charged at the input rate, so the corrected figure can be slightly low for cache-write-heavy traffic.
- [Buckets that cannot be proven keep inflated pruned-row totals] → This is limited to buckets with an account, an unpriced successful request, a mixed-rate model, or a row whose cost fails the proof. On a copy of the database of the deployment that found the bug, 2 hourly buckets stay inflated, `$2.52` in total against `$0.93` at the published rate. Both are account buckets.
- [Retention pauses until the repair finishes] → The repair processes bounded chunks on each fold pass, and pruning resumes on the next retention pass after it finishes.

## Migration Plan

1. Deploy the code and revision. Startup runs the migration, and the next fold passes refold the marked range.
2. Run `codex-lb model-prices refresh` once, so records without a seeded rate read their catalog's cache-read rate.
3. Rollback is a code revert. Corrected costs stay, and the column is dropped by `downgrade()`.

## Open Questions

- none
