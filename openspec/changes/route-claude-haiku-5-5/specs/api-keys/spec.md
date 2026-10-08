## ADDED Requirements

### Requirement: Claude Haiku 5.5 pricing resolves the 5.5 identity

The native price table MUST price `claude-haiku-5-5`, including one leading `cc/`, `cp-`, or `cp_` prefix on that exact id, by prompt length. A request whose input tokens, cached tokens included, are at most 100,000 MUST use $0.10 input, $0.01 cache-hit, and $0.50 output per 1M tokens. A request over 100,000 input tokens MUST use $0.50 input, $0.05 cache-hit, and $2.50 output per 1M tokens for all of its tokens, output included. The resolved canonical model MUST be `claude-haiku-5-5`. It MUST NOT price a dotted, dated, or effort-suffixed spelling as `claude-haiku-5-5`. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A longer id MUST NOT inherit a shorter family's price. When a supplied price table has no entry for that exact id, lookup MUST return no price.

#### Scenario: Canonical Haiku 5.5 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-haiku-5-5` with token usage
- **THEN** it uses the Haiku 5.5 short-prompt rates ($0.10 input / $0.01 cache-hit / $0.50 output per 1M tokens)
- **AND** the resolved canonical model is `claude-haiku-5-5`

#### Scenario: Sidecar-prefixed Haiku 5.5 resolves Haiku 5.5 pricing

- **WHEN** native price lookup receives model `cc/claude-haiku-5-5`
- **THEN** it resolves the Haiku 5.5 native price entry
- **AND** the resolved canonical model is `claude-haiku-5-5`

#### Scenario: Dotted and dated Haiku 5.5 spellings do not use the hyphen entry

- **WHEN** native price lookup receives model `claude-haiku-5.5` or `claude-haiku-5-5-20261007`
- **THEN** it does not resolve the canonical model `claude-haiku-5-5`

#### Scenario: A price table without the version does not inherit the family price

- **WHEN** native price lookup receives model `cc/claude-haiku-5-5`
- **AND** the supplied price table contains only `claude-haiku-4-5`
- **THEN** it returns no price

#### Scenario: A Haiku 5.5 lookalike does not use the Haiku 5.5 entry

- **WHEN** native price lookup receives model `claude-haiku-5-50` or `not-claude-haiku-5-5`
- **THEN** it does not resolve the canonical model `claude-haiku-5-5` or `claude-haiku-4-5`

#### Scenario: A Haiku 5.5 prompt over 100,000 tokens uses the long-prompt rates

- **WHEN** native cost accounting prices `claude-haiku-5-5` usage with 100,001 input tokens, 60,000 of them cached, and 10,000 output tokens
- **THEN** it charges $0.50 per 1M uncached input, $0.05 per 1M cached input, and $2.50 per 1M output

#### Scenario: A Haiku 5.5 prompt of exactly 100,000 tokens uses the short-prompt rates

- **WHEN** native cost accounting prices `claude-haiku-5-5` usage with exactly 100,000 input tokens
- **THEN** it charges the short-prompt rates

## MODIFIED Requirements

### Requirement: Claude Sonnet 5.5 pricing resolves the 5.5 identity

The native price table MUST price `claude-sonnet-5-5`, including one leading `cc/`, `cp-`, or `cp_` prefix on that exact id, at $2 input, $0.10 cache-hit, and $10 output per 1M tokens. The resolved canonical model MUST be `claude-sonnet-5-5`. It MUST NOT price a dotted, dated, or effort-suffixed spelling as `claude-sonnet-5-5`. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A longer id MUST NOT inherit a shorter family's price. When a supplied price table has no entry for that exact id, lookup MUST return no price.

#### Scenario: Canonical Sonnet 5.5 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-sonnet-5-5` with token usage
- **THEN** it uses the Sonnet 5.5 native rates ($2 input / $0.10 cache-hit / $10 output per 1M tokens)
- **AND** the resolved canonical model is `claude-sonnet-5-5`

#### Scenario: Sidecar-prefixed Sonnet 5.5 does not resolve as Sonnet 5

- **WHEN** native price lookup receives model `cc/claude-sonnet-5-5`
- **THEN** it resolves the Sonnet 5.5 native price entry
- **AND** the resolved canonical model is `claude-sonnet-5-5`

#### Scenario: Dotted and dated Sonnet 5.5 spellings do not use the hyphen entry

- **WHEN** native price lookup receives model `claude-sonnet-5.5` or `claude-sonnet-5-5-20260928`
- **THEN** it does not resolve the canonical model `claude-sonnet-5-5`

#### Scenario: A price table without the version does not inherit the family price

- **WHEN** native price lookup receives model `cc/claude-sonnet-5-5`
- **AND** the supplied price table contains only `claude-sonnet-5`
- **THEN** it returns no price

#### Scenario: A Sonnet 5.5 lookalike does not use the Sonnet 5.5 entry

- **WHEN** native price lookup receives model `claude-sonnet-5-50` or `not-claude-sonnet-5-5`
- **THEN** it does not resolve the canonical model `claude-sonnet-5-5` or `claude-sonnet-5`
