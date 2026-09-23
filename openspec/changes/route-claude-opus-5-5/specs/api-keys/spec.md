## ADDED Requirements

### Requirement: Claude Opus 5.5 pricing is distinct from Opus 5

The native price table MUST recognize Anthropic Claude Opus 5.5, including sidecar-prefixed and dotted ids such as `cc/claude-opus-5-5` and `claude-opus-5.5`. Its rates MUST remain distinct from Opus 5: $4 input, $0.20 cache-hit, and $20 output per 1M tokens. External integration request-log costs remain governed by `external-model-pricing`: catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A recognized version MUST NOT remove pricing that a price table would otherwise supply. When a supplied price table has no entry for the resolved version, lookup MUST fall back to the legacy family alias so the request is still priced instead of silently losing its cost.

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

#### Scenario: A price table without the version still prices the request

- **WHEN** native price lookup receives model `cc/claude-opus-5-5`
- **AND** the supplied price table contains only `claude-opus-5`
- **THEN** it resolves the `claude-opus-5` entry rather than returning no price

#### Scenario: An Opus 5.5 lookalike does not use the Opus 5.5 entry

- **WHEN** native price lookup receives model `claude-opus-5-50` or `not-claude-opus-5-5`
- **THEN** it does not resolve the canonical model `claude-opus-5-5`

### Requirement: An Opus 5 allowlist does not admit Opus 5.5

An API key whose `allowed_models` names only `claude-opus-5` MUST NOT gain access to Claude Opus 5.5. A key whose `allowed_models` names `claude-opus-5-5` MUST admit dotted and sidecar-prefixed Opus 5.5 ids. Lookalike ids that are not Opus 5.5 MUST NOT resolve to the Opus 5.5 identity.

#### Scenario: An Opus 5 allowlist rejects Opus 5.5

- **WHEN** an API key whose `allowed_models` is exactly `claude-opus-5` requests `cc/claude-opus-5-5`
- **THEN** the request is refused as not allowed for that key

#### Scenario: An Opus 5 allowlist still admits Opus 5

- **WHEN** the same API key requests `cc/claude-opus-5`
- **THEN** the request is allowed

#### Scenario: An allowlist naming Opus 5.5 admits dotted and prefixed ids

- **WHEN** an API key whose `allowed_models` is exactly `claude-opus-5-5` requests `claude-opus-5.5` or `cc/claude-opus-5-5`
- **THEN** the request is allowed
