# Tasks

## 1. Runtime pricing from OpenRouter
- [x] 1.1 Add pricing fields to `SidecarModel` (or a parallel structure) to carry parsed `ModelPrice`.
- [x] 1.2 Parse `pricing.prompt`/`completion`/`input_cache_read` (USD-per-token strings) into per-1M `ModelPrice` in `openrouter_sidecar.py`.
- [x] 1.3 Add a runtime pricing registry overlaying `DEFAULT_PRICING_MODELS`, populated from `list_models()`.
- [x] 1.4 Add `get_reference_pricing_for_model` with free->paid resolution (strip `:free`/`-free`/`_free`).
- [x] 1.5 Unit tests for parsing, overlay precedence, and free->paid resolution.

## 2. Schema + persistence
- [x] 2.1 Add nullable `reference_cost_usd` column to `RequestLog` model.
- [x] 2.2 Add Alembic migration (single head on current parent) adding the column, with downgrade.
- [x] 2.3 Add `reference_cost_usd` parameter to `RequestLogsRepository.add_log` and persist it.
- [x] 2.4 Migration test coverage (column added + nullable).

## 3. Dispatch
- [x] 3.1 Compute `reference_cost_usd` from resolved reference price x actual usage in OpenRouter dispatch and pass to `add_log`.
- [x] 3.2 Same for OmniRoute dispatch.
- [x] 3.3 Unit tests asserting free-model requests record reference cost while `cost_usd` stays 0.

## 4. Aggregation + serialization
- [x] 4.1 Expose `reference_cost_usd` and derived `savings_usd` in request-log serialization.
- [x] 4.2 Add total savings to usage aggregation (per-source summary).
- [x] 4.3 Plumb savings through dashboard service / schemas.
- [x] 4.4 Tests for serialization (mapper) and aggregation (summary).

## 5. Frontend
- [x] 5.1 Display total savings on the dashboard account card.
- [x] 5.2 Frontend tests.

## 6. Validation
- [x] 6.1 `openspec validate add-sidecar-reference-cost-savings --strict`
- [x] 6.2 `uv run pytest` for touched areas; `npx vitest run` for touched frontend.
- [x] 6.3 `ruff` clean on changed files (pre-existing unrelated lint left untouched).
