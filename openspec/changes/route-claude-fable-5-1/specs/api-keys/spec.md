## ADDED Requirements

### Requirement: GPT-6 Astra native usage cost pricing preserves reconciled rates

When computing native API-key usage, request-log, reservation, or aggregate cost for `gpt-6-astra`, the system MUST use these reconciled USD-per-1M-token rates for input, cached input, and output. External integration costs remain governed by `external-model-pricing`, not this native table:

| Model | Standard | Fast/priority | Flex | Standard long context |
| --- | --- | --- | --- | --- |
| `gpt-6-astra` | `10 / 1 / 50` | `20 / 2 / 100` | `5 / 0.50 / 25` | `20 / 2 / 75` |

The existing `priority` and `fast` service-tier aliases MUST use the Fast/priority rates. Standard long-context rates MUST apply only when input tokens exceed 272,000. Flex long-context pricing MUST continue to use the existing Flex short-context rates and multipliers. Suffixed aliases such as `gpt-6-astra-2026-09-03` and the discoverable alias `codex/gpt-6-astra` MUST resolve to the canonical `gpt-6-astra` price entry.

#### Scenario: Astra standard usage uses the reconciled rate

- **WHEN** a standard-tier `gpt-6-astra` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **THEN** the token cost is `$51.10`

#### Scenario: Astra Fast and Flex usage use their tier rates

- **WHEN** a `gpt-6-astra` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **AND** the request uses `priority` or `fast`
- **THEN** the token cost is `$102.20`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$25.55`

#### Scenario: Astra standard long-context usage uses the long-context rate

- **WHEN** a standard-tier `gpt-6-astra` request has 300,000 input tokens, 50,000 cached input tokens, and 100,000 output tokens
- **THEN** the token cost is `$12.60`

### Requirement: Claude Fable 5.1 pricing is distinct from Fable 5

The native price table MUST recognize Anthropic Claude Fable 5.1, including sidecar-prefixed and dotted ids such as `cc/claude-fable-5-1` and `cc/claude-fable-5.1`. Its cache-read rate MUST remain distinct from Fable 5's. External integration request-log costs remain governed by `external-model-pricing`: catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A recognized version MUST NOT remove pricing that a price table would otherwise supply. When a supplied price table has no entry for the resolved version, lookup MUST fall back to the legacy family alias so the request is still priced instead of silently losing its cost.

#### Scenario: Canonical Fable 5.1 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-fable-5-1` with token usage
- **THEN** it uses the reconciled Fable 5.1 native rates ($10 input / $0.25 cache-hit / $50 output per 1M tokens)

#### Scenario: Sidecar-prefixed Fable 5.1 does not use Fable 5 cache-hit pricing

- **WHEN** native price lookup receives model `cc/claude-fable-5-1`
- **THEN** it resolves the distinct Fable 5.1 native price entry
- **AND** the resolved canonical model is `claude-fable-5-1`

#### Scenario: A price table without the version still prices the request

- **WHEN** native price lookup receives model `cc/claude-fable-5-1`
- **AND** the supplied price table contains only `claude-fable-5`
- **THEN** it resolves the `claude-fable-5` entry rather than returning no price

### Requirement: API-key model access does not treat distinct sidecar integrations as the same model

`allowed_models` enforcement MUST retain the owning sidecar integration when comparing routed identities. A key whose allowlist names a model only through one integration's prefix or full-model id MUST NOT be granted access to the same wire model on a different enabled sidecar integration. An allowlist that names the unprefixed wire model MUST still admit prefixed requests that resolve to that wire model. Conversely, an allowlist entry bound to one integration MUST NOT admit a request that resolves to no route, because such a request reaches the default dispatch path rather than the granted integration.

#### Scenario: A Claude-prefixed allowlist rejects the same slug on OpenRouter

- **GIVEN** Claude routing prefix `cc/` and OpenRouter routing prefix `or/` both strip
- **WHEN** an API key whose `allowed_models` is exactly `cc/custom-slug` requests `or/custom-slug`
- **THEN** the request is refused before quota reservation or upstream traffic

#### Scenario: The same Claude prefix still admits that slug

- **WHEN** the same API key requests `cc/custom-slug`
- **THEN** the request is allowed

#### Scenario: An unprefixed allowlist still admits a prefixed request for that wire model

- **GIVEN** Claude routing prefix `cp-` with stripping enabled
- **WHEN** an API key whose `allowed_models` is exactly `claude-opus-4-7` requests `cp-claude-opus-4-7`
- **THEN** the request is allowed

#### Scenario: An integration-bound allowlist rejects an unrouted request for the same wire model

- **GIVEN** Claude routing prefix `cc/` with stripping enabled
- **WHEN** an API key whose `allowed_models` is exactly `cc/custom-slug` requests the bare `custom-slug`, which resolves no route
- **THEN** the request is refused before quota reservation or upstream traffic

## API-key model access reference

The authoritative requirement and scenarios, including configured prefix resolution before reservation and dispatch, are maintained in [API-key model access](../../../../specs/api-keys/spec.md#requirement-api-key-model-access-does-not-collapse-a-separately-priced-version-into-its-family).
