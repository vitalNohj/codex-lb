## Why

OpenAI-compatible Unlid endpoints publish rates under `data[].unlid.pricing` in USD per million tokens. The existing reader only understands top-level OpenRouter-style per-token `pricing`, so Unlid requests settle as not token priced and log no cost despite a published rate.

## What Changes

- Recognize Unlid's explicit namespaced pricing format without new endpoint settings or hardcoded model prices.
- Use the same format-aware reader for runtime reference pricing and the endpoint's serving catalog.
- Preserve the distinction between absent token rates and unreadable published rates.
- Document the explicit refresh needed for records previously settled as not token priced.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `external-model-pricing`: generic OpenAI-compatible endpoints recognize OpenRouter and Unlid pricing formats with explicit units and deterministic precedence.

## Impact

- Core catalog parsing, OpenAI-compatible model client, and serving-catalog loader.
- Unit and integration coverage, pricing documentation.
- No database migration, UI change, new background schedule, historical request repricing, or change to billed-cost provenance. Deployment and service restart require operator approval.
