## Why

A newly discovered Claude release already gets catalog pricing, but its vision advertisement and output bounds still depend on fixed model lists. Claude Fable 5.2 therefore advertises text-only input and misses the output floor even though models.dev publishes its modalities and limits.

## What Changes

- Retain validated Anthropic input modalities and context/output limits from the existing models.dev metadata fetch, without adding request-path network I/O.
- Advertise those modalities and image/vision support for exact Claude sidecar ids, including one leading `cc/`, `cp-`, or `cp_` routing prefix.
- Derive output bounds from catalog limits only when no fixed bounds row exists; retain the existing 32,768-token floor and all existing guards.
- Persist last-good capability metadata alongside pricing. Preserve existing behavior when neither cached nor bundled metadata knows the model.
- Keep dotted, dated, and effort-suffixed ids distinct. Do not change pricing, routing, fixed bounds, or dashboard UI.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `upstream-metadata`: retain public Claude capability metadata with offline fallbacks and use exact-id metadata for sidecar advertisements and fallback output bounds.

## Impact

- Metadata catalog parsing, refresh, and the backward-compatible pricing cache payload.
- Claude sidecar capability advertisement and output-bound lookup.
- Deterministic parser, refresh/offline-restart, dispatch, and model-list tests.
- No database migration, new remote endpoint, pricing policy change, or live service operation.
