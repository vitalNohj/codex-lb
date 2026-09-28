## ADDED Requirements

### Requirement: Claude price lookup matches the same id after prefix, date, and effort decoration

Native Claude price lookup MUST resolve a prefixed, date-stamped, or effort-suffixed spelling of an existing price key by exact match after removing one leading `cc/`, `cp-`, or `cp_` prefix, one trailing release date (`-YYYYMMDD` or `-YYYY-MM-DD`), and one trailing reasoning-effort suffix. A longer id MUST NOT inherit a shorter family's price. A supplied price table that lacks the resolved id MUST return no price for that id. An API key whose `allowed_models` names a Claude price key MUST admit those same decorated spellings and MUST NOT admit a longer id that merely contains the key.

#### Scenario: Prefixed and dated spellings use the existing key

- **WHEN** native price lookup receives `cp-claude-opus-4-7` or `claude-opus-4-5-20251101`
- **THEN** it resolves `claude-opus-4-7` or `claude-opus-4-5` respectively

#### Scenario: A longer sibling does not inherit the shorter price

- **WHEN** native price lookup receives `cc/claude-sonnet-5-5`, `claude-sonnet-5-50`, or `not-claude-sonnet-5-5`
- **AND** the supplied price table contains only `claude-sonnet-5`
- **THEN** none of those ids resolve the `claude-sonnet-5` entry

#### Scenario: A family grant rejects a longer lookalike

- **WHEN** an API key whose `allowed_models` is exactly `claude-sonnet-5` requests `claude-sonnet-5-50` or `not-claude-sonnet-5-5`
- **THEN** the request is refused as not allowed for that key

## MODIFIED Requirements

### Requirement: Claude Fable 5.1 pricing is distinct from Fable 5

The native price table MUST recognize Anthropic Claude Fable 5.1, including sidecar-prefixed and dotted ids such as `cc/claude-fable-5-1` and `cc/claude-fable-5.1`. Its cache-read rate MUST remain distinct from Fable 5's. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A recognized version MUST NOT inherit a shorter family's price. When a supplied price table has no entry for the resolved version, lookup MUST return no price for that id.

#### Scenario: Canonical Fable 5.1 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-fable-5-1` with token usage
- **THEN** it uses the preserved Fable 5.1 native rates ($10 input / $0.25 cache-hit / $50 output per 1M tokens)

#### Scenario: Sidecar-prefixed Fable 5.1 does not use Fable 5 cache-hit pricing

- **WHEN** native price lookup receives model `cc/claude-fable-5-1`
- **THEN** it resolves the distinct Fable 5.1 native price entry
- **AND** the resolved canonical model is `claude-fable-5-1`

#### Scenario: A price table without the version does not inherit the family price

- **WHEN** native price lookup receives model `cc/claude-fable-5-1`
- **AND** the supplied price table contains only `claude-fable-5`
- **THEN** it returns no price

### Requirement: Claude Opus 5.5 pricing is distinct from Opus 5

The native price table MUST recognize Anthropic Claude Opus 5.5, including sidecar-prefixed and dotted ids such as `cc/claude-opus-5-5` and `claude-opus-5.5`. Its rates MUST remain distinct from Opus 5: $4 input, $0.20 cache-hit, and $20 output per 1M tokens. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A recognized version MUST NOT inherit a shorter family's price. When a supplied price table has no entry for the resolved version, lookup MUST return no price for that id.

#### Scenario: Canonical Opus 5.5 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-opus-5-5` with token usage
- **THEN** it uses the Opus 5.5 native rates ($4 input / $0.20 cache-hit / $20 output per 1M tokens)

#### Scenario: Sidecar-prefixed Opus 5.5 does not use Opus 5 cache-hit pricing

- **WHEN** native price lookup receives model `cc/claude-opus-5-5`
- **THEN** it resolves the distinct Opus 5.5 native price entry
- **AND** the resolved canonical model is `claude-opus-5-5`

#### Scenario: Dotted and dated Opus 5.5 ids use the Opus 5.5 entry

- **WHEN** native price lookup receives model `claude-opus-5.5` or `claude-opus-5-5-20260922`
- **THEN** the resolved canonical model is `claude-opus-5-5`

#### Scenario: A price table without the version does not inherit the family price

- **WHEN** native price lookup receives model `cc/claude-opus-5-5`
- **AND** the supplied price table contains only `claude-opus-5`
- **THEN** it returns no price

#### Scenario: An Opus 5.5 lookalike does not use the Opus 5.5 entry

- **WHEN** native price lookup receives model `claude-opus-5-50` or `not-claude-opus-5-5`
- **THEN** it does not resolve the canonical model `claude-opus-5-5` or `claude-opus-5`

### Requirement: Claude Sonnet 5.5 pricing resolves the 5.5 identity

The native price table MUST recognize Anthropic Claude Sonnet 5.5, including sidecar-prefixed and dotted ids such as `cc/claude-sonnet-5-5` and `claude-sonnet-5.5`. Its rates MUST be $2 input, $0.20 cache-hit, and $10 output per 1M tokens, and the resolved canonical model MUST be `claude-sonnet-5-5`. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A recognized version MUST NOT inherit a shorter family's price. When a supplied price table has no entry for the resolved version, lookup MUST return no price for that id.

#### Scenario: Canonical Sonnet 5.5 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-sonnet-5-5` with token usage
- **THEN** it uses the Sonnet 5.5 native rates ($2 input / $0.20 cache-hit / $10 output per 1M tokens)
- **AND** the resolved canonical model is `claude-sonnet-5-5`

#### Scenario: Sidecar-prefixed Sonnet 5.5 does not resolve as Sonnet 5

- **WHEN** native price lookup receives model `cc/claude-sonnet-5-5`
- **THEN** it resolves the Sonnet 5.5 native price entry
- **AND** the resolved canonical model is `claude-sonnet-5-5`

#### Scenario: Dotted and dated Sonnet 5.5 ids use the Sonnet 5.5 entry

- **WHEN** native price lookup receives model `claude-sonnet-5.5` or `claude-sonnet-5-5-20260928`
- **THEN** the resolved canonical model is `claude-sonnet-5-5`

#### Scenario: A price table without the version does not inherit the family price

- **WHEN** native price lookup receives model `cc/claude-sonnet-5-5`
- **AND** the supplied price table contains only `claude-sonnet-5`
- **THEN** it returns no price

#### Scenario: A Sonnet 5.5 lookalike does not use the Sonnet 5.5 entry

- **WHEN** native price lookup receives model `claude-sonnet-5-50` or `not-claude-sonnet-5-5`
- **THEN** it does not resolve the canonical model `claude-sonnet-5-5` or `claude-sonnet-5`
