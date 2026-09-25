## Context

OpenAI-compatible sidecars parse top-level OpenRouter-style per-token `pricing`. Unlid's `/models` instead publishes `unlid.pricing` with explicit USD-per-million fields. Both the model client's runtime price registry and the serving catalog must use the same interpretation. A model listed with no recognized rate currently settles as `not_token_priced`, so a change to the parser alone does not repair persisted records.

## Goals / Non-Goals

**Goals:**

- Price Unlid models using published input/output rates for requests with recorded token usage.
- Distinguish an unreadable rate from an explicitly missing rate so an upstream shape error cannot silently settle as no token price.
- Keep OpenRouter-style and unpriced generic OpenAI-compatible endpoints working as before.
- Support a manual refresh transition for records previously settled by the old reader.

**Non-Goals:**

- Treating Unlid's per-request `unlid.cost_usd` as upstream-billed, changing provenance, or backfilling historical request logs.
- Persisting separate cached-input rates (the existing external price store prices cached input at the full input rate).
- A new UI setting, background price polling, live deployment, or changing model routing.

## Decisions

- A format descriptor specifies input/output/cache-read keys and the multiplier into USD per million. The shared rate reader preserves nonnegative finite numeric rates including zero, numeric strings, and its established explicit-null/negative-sentinel vs unreadable distinction.
- The OpenAI-compatible client selects the top-level pricing block when non-null, then Unlid's namespaced block, and otherwise treats the entry as not token priced. It does not infer units from arbitrary provider fields. The same selector feeds the client runtime registry and the serving catalog; a malformed present block is not silently replaced by a secondary price.
- The serving catalog parses input/output rates but intentionally leaves cached input at the full input rate under the existing store/spec contract. The runtime registry can carry a published cache-read rate for reference-cost calculation.
- Keep the existing pre-parsed sidecar catalog builder and reference-catalog parser behavior intact. Introduce a block-based builder for OpenAI-compatible listings rather than recoding other sidecars.

## Verification

- Replay a captured Unlid `/models` response behind a local HTTP server and send normal and streamed chat completions through a local codex-lb server. Check the persisted price status, rates, cost, and provenance before/after the change.
- Verify an old settled `not_token_priced` record becomes resolved via `codex-lb model-prices refresh` after the change.
- Add deterministic unit and integration tests for valid, free, absent, malformed, mixed-format, and prior-runtime-price cases.

## Risks / Trade-offs

- A provider changes its price schema: unreadable blocks and nonempty Unlid pricing objects with unknown rate keys remain retryable; entirely absent pricing remains a settled no-rate answer as for other serving catalogs. An explicit refresh is required for previously settled records.
- Actual billed cost can differ due to caching or other billing rules. Catalog-calculated provenance remains visible; billed-cost recognition is a separate feature.
