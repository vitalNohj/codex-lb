## Why

GPT-5.6 Sol, Terra, and Luna need canonical pricing entries so request-log costs and API-key `cost_usd` quota settlement do not fall through the shared `gpt-5*` alias. An earlier landing of those entries used provisional Terra/Luna rates that no longer match the published OpenAI table (Luna was 5× too high; Terra was 25% too high), which made cheap Luna traffic look like "$0.00" in 2-decimal currency formatting and overstated quota burn.

## What Changes

- add canonical standard, Flex, Priority/Fast, and long-context prices for `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` using the published OpenAI rates
- map the bare `gpt-5.6` alias to Sol and add wildcard aliases so suffixed personality model IDs resolve to the matching canonical pricing entry
- add regression coverage for canonical resolution and tier-specific cost calculations
- leave cache-write-token pricing out of scope until the usage model exposes cache-write tokens separately
- show sub-cent USD amounts with enough fraction digits so Luna request-log costs do not round to `$0.00`

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `api-keys`: cost accounting must recognize the bare GPT-5.6 alias, the three personality models, their suffixed aliases, service tiers, and published long-context rates

## Impact

- Code: `app/core/usage/pricing.py`
- Tests: `tests/unit/test_pricing.py`, `tests/unit/test_api_keys_service.py`
- Specs: `openspec/specs/api-keys/spec.md` via this change's delta spec
- No API or database schema changes
