## 1. Runtime pricing

- [x] 1.1 Keep the published cache-read rate in `parse_published_pricing` and in OpenAI-compatible published catalogs
- [x] 1.2 Mark an entry unparseable when its cache-read rate is present but unreadable, or any parsed rate is non-finite
- [x] 1.3 Add `external_model_prices.cached_input_per_1m` and thread it through every store writer and `PriceRecord.price`
- [x] 1.4 Compare, apply, and report cache-read rates in the maintenance refresh

## 2. Historical correction

- [x] 2.1 Alembic revision on `20260928_000000_pin_claude_sonnet_5_5_full_model` that adds the column and seeds records priced from the OpenRouter reference out of a dated 2026-10-03 card snapshot
- [x] 2.2 Reprice `catalog_calculated` rows that provably store the full-rate figure, with exact lifetime account and API-key deltas
- [x] 2.3 Arm `upgrade_repair_from` for refoldable buckets, and correct buckets below the refold floor only on proof
- [x] 2.4 Keep corrected costs on downgrade, and make a rerun change nothing
- [x] 2.5 Pause request-log retention while `upgrade_repair_from` is set

## 3. Regression coverage

- [x] 3.1 Catalog parsing: published, absent, declared-none, and unreadable cache-read rates, for OpenRouter, sidecar, and Unlid shapes
- [x] 3.2 Request path and end-to-end Claude sidecar cost at the published cache-read rate
- [x] 3.3 Maintenance: a newly published, a withdrawn, and an unreadable cache-read rate
- [x] 3.4 Retention stays paused while a repair is pending and resumes after it
- [x] 3.5 Migration: row repricing, lifetime deltas, bucket proof below the refold floor, downgrade, and rerun
- [x] 3.6 Update tests that asserted the old full-rate rule

## 4. Docs and verification

- [x] 4.1 Update `docs/model-pricing.md` and the `external-model-pricing` and `data-retention` specs and context
- [ ] 4.2 `openspec validate price-external-cache-reads --strict`
- [ ] 4.3 `ruff`, `ty`, and the affected pytest modules
