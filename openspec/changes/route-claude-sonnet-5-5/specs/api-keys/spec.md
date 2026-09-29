## ADDED Requirements

### Requirement: Claude Sonnet 5.5 pricing resolves the 5.5 identity

The native price table MUST recognize Anthropic Claude Sonnet 5.5, including sidecar-prefixed and dotted ids such as `cc/claude-sonnet-5-5` and `claude-sonnet-5.5`. Its rates MUST be $2 input, $0.20 cache-hit, and $10 output per 1M tokens, and the resolved canonical model MUST be `claude-sonnet-5-5`. External integration request-log costs remain governed by `external-model-pricing`: catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A recognized version MUST NOT remove pricing that a price table would otherwise supply. When a supplied price table has no entry for the resolved version, lookup MUST fall back to the legacy family alias so the request is still priced instead of silently losing its cost.

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

#### Scenario: A price table without the version still prices the request

- **WHEN** native price lookup receives model `cc/claude-sonnet-5-5`
- **AND** the supplied price table contains only `claude-sonnet-5`
- **THEN** it resolves the `claude-sonnet-5` entry rather than returning no price

#### Scenario: A Sonnet 5.5 lookalike does not use the Sonnet 5.5 entry

- **WHEN** native price lookup receives model `claude-sonnet-5-50` or `not-claude-sonnet-5-5`
- **THEN** it does not resolve the canonical model `claude-sonnet-5-5`

### Requirement: A Sonnet 5 allowlist does not admit Sonnet 5.5

An API key whose `allowed_models` names only `claude-sonnet-5` MUST NOT gain access to Claude Sonnet 5.5. A key whose `allowed_models` names `claude-sonnet-5-5` MUST admit dotted and sidecar-prefixed Sonnet 5.5 ids. Lookalike ids that are not Sonnet 5.5 MUST NOT resolve to the Sonnet 5.5 identity.

#### Scenario: A Sonnet 5 allowlist rejects Sonnet 5.5

- **WHEN** an API key whose `allowed_models` is exactly `claude-sonnet-5` requests `cc/claude-sonnet-5-5`
- **THEN** the request is refused as not allowed for that key

#### Scenario: A Sonnet 5 allowlist still admits Sonnet 5

- **WHEN** the same API key requests `cc/claude-sonnet-5`
- **THEN** the request is allowed

#### Scenario: An allowlist naming Sonnet 5.5 admits dotted and prefixed ids

- **WHEN** an API key whose `allowed_models` is exactly `claude-sonnet-5-5` requests `claude-sonnet-5.5` or `cc/claude-sonnet-5-5`
- **THEN** the request is allowed
