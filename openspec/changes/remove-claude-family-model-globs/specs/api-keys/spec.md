## MODIFIED Requirements

### Requirement: Claude Fable 5.1 pricing is distinct from Fable 5

The native price table MUST price `claude-fable-5-1`, including one leading `cc/`, `cp-`, or `cp_` prefix on that exact id, at the Fable 5.1 rates. It MUST NOT price dotted `claude-fable-5.1` as `claude-fable-5-1`. Its cache-read rate MUST remain distinct from Fable 5's. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A longer id MUST NOT inherit a shorter family's price. When a supplied price table has no entry for that exact id, lookup MUST return no price.

#### Scenario: Canonical Fable 5.1 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-fable-5-1` with token usage
- **THEN** it uses the preserved Fable 5.1 native rates ($10 input / $0.25 cache-hit / $50 output per 1M tokens)

#### Scenario: Sidecar-prefixed Fable 5.1 does not use Fable 5 cache-hit pricing

- **WHEN** native price lookup receives model `cc/claude-fable-5-1`
- **THEN** it resolves the distinct Fable 5.1 native price entry
- **AND** the resolved canonical model is `claude-fable-5-1`

#### Scenario: A dotted Fable spelling does not use the hyphen entry

- **WHEN** native price lookup receives model `claude-fable-5.1` or `cc/claude-fable-5.1`
- **THEN** it does not resolve the canonical model `claude-fable-5-1`

#### Scenario: A price table without the version does not inherit the family price

- **WHEN** native price lookup receives model `cc/claude-fable-5-1`
- **AND** the supplied price table contains only `claude-fable-5`
- **THEN** it returns no price

### Requirement: Claude Opus 5.5 pricing is distinct from Opus 5

The native price table MUST price `claude-opus-5-5`, including one leading `cc/`, `cp-`, or `cp_` prefix on that exact id, at rates distinct from Opus 5: $4 input, $0.20 cache-hit, and $20 output per 1M tokens. It MUST NOT price a dotted, dated, or effort-suffixed spelling as `claude-opus-5-5`. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A longer id MUST NOT inherit a shorter family's price. When a supplied price table has no entry for that exact id, lookup MUST return no price.

#### Scenario: Canonical Opus 5.5 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-opus-5-5` with token usage
- **THEN** it uses the Opus 5.5 native rates ($4 input / $0.20 cache-hit / $20 output per 1M tokens)

#### Scenario: Sidecar-prefixed Opus 5.5 does not use Opus 5 cache-hit pricing

- **WHEN** native price lookup receives model `cc/claude-opus-5-5`
- **THEN** it resolves the distinct Opus 5.5 native price entry
- **AND** the resolved canonical model is `claude-opus-5-5`

#### Scenario: Dotted and dated Opus 5.5 spellings do not use the hyphen entry

- **WHEN** native price lookup receives model `claude-opus-5.5` or `claude-opus-5-5-20260922`
- **THEN** it does not resolve the canonical model `claude-opus-5-5`

#### Scenario: A price table without the version does not inherit the family price

- **WHEN** native price lookup receives model `cc/claude-opus-5-5`
- **AND** the supplied price table contains only `claude-opus-5`
- **THEN** it returns no price

#### Scenario: An Opus 5.5 lookalike does not use the Opus 5.5 entry

- **WHEN** native price lookup receives model `claude-opus-5-50` or `not-claude-opus-5-5`
- **THEN** it does not resolve the canonical model `claude-opus-5-5` or `claude-opus-5`

### Requirement: Claude Sonnet 5.5 pricing resolves the 5.5 identity

The native price table MUST price `claude-sonnet-5-5`, including one leading `cc/`, `cp-`, or `cp_` prefix on that exact id, at $2 input, $0.20 cache-hit, and $10 output per 1M tokens. The resolved canonical model MUST be `claude-sonnet-5-5`. It MUST NOT price a dotted, dated, or effort-suffixed spelling as `claude-sonnet-5-5`. External integration request-log costs remain governed by [external-model-pricing](../external-model-pricing/spec.md): catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

A longer id MUST NOT inherit a shorter family's price. When a supplied price table has no entry for that exact id, lookup MUST return no price.

#### Scenario: Canonical Sonnet 5.5 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-sonnet-5-5` with token usage
- **THEN** it uses the Sonnet 5.5 native rates ($2 input / $0.20 cache-hit / $10 output per 1M tokens)
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

### Requirement: An Opus 5 allowlist does not admit Opus 5.5

An API key whose `allowed_models` names only `claude-opus-5` MUST NOT gain access to Claude Opus 5.5. A key whose `allowed_models` names `claude-opus-5-5` MUST admit that exact id and the same id with one leading `cc/`, `cp-`, or `cp_` prefix. It MUST NOT admit a dotted, dated, or effort-suffixed spelling. Lookalike ids that are not Opus 5.5 MUST NOT resolve to the Opus 5.5 identity.

#### Scenario: An Opus 5 allowlist rejects Opus 5.5

- **WHEN** an API key whose `allowed_models` is exactly `claude-opus-5` requests `cc/claude-opus-5-5`
- **THEN** the request is refused as not allowed for that key

#### Scenario: An Opus 5 allowlist still admits Opus 5

- **WHEN** the same API key requests `cc/claude-opus-5`
- **THEN** the request is allowed

#### Scenario: An allowlist naming Opus 5.5 admits the prefixed id

- **WHEN** an API key whose `allowed_models` is exactly `claude-opus-5-5` requests `cc/claude-opus-5-5`
- **THEN** the request is allowed

#### Scenario: An allowlist naming Opus 5.5 rejects a dotted spelling

- **WHEN** an API key whose `allowed_models` is exactly `claude-opus-5-5` requests `claude-opus-5.5`
- **THEN** the request is refused as not allowed for that key

### Requirement: A Sonnet 5 allowlist does not admit Sonnet 5.5

An API key whose `allowed_models` names only `claude-sonnet-5` MUST NOT gain access to Claude Sonnet 5.5. A key whose `allowed_models` names `claude-sonnet-5-5` MUST admit that exact id. When `cc/` resolves to the Claude integration, a key whose `allowed_models` names `cc/claude-sonnet-5-5` MUST admit that request, and a bare `claude-sonnet-5-5` grant MUST NOT. It MUST NOT admit a dotted, dated, or effort-suffixed spelling. Lookalike ids that are not Sonnet 5.5 MUST NOT resolve to the Sonnet 5.5 identity.

#### Scenario: A Sonnet 5 allowlist rejects Sonnet 5.5

- **WHEN** an API key whose `allowed_models` is exactly `claude-sonnet-5` requests `cc/claude-sonnet-5-5`
- **THEN** the request is refused as not allowed for that key

#### Scenario: A Sonnet 5 allowlist still admits Sonnet 5

- **WHEN** the same API key requests `cc/claude-sonnet-5`
- **THEN** the request is allowed

#### Scenario: An allowlist naming the routed Sonnet 5.5 id admits that request

- **GIVEN** the Claude routing prefix `cc/` strips
- **WHEN** an API key whose `allowed_models` is exactly `cc/claude-sonnet-5-5` requests `cc/claude-sonnet-5-5`
- **THEN** the request is allowed

#### Scenario: A bare Sonnet 5.5 grant rejects the routed prefix

- **GIVEN** the Claude routing prefix `cc/` strips
- **WHEN** an API key whose `allowed_models` is exactly `claude-sonnet-5-5` requests `cc/claude-sonnet-5-5`
- **THEN** the request is refused as not allowed for that key

#### Scenario: An allowlist naming Sonnet 5.5 rejects a dotted spelling

- **WHEN** an API key whose `allowed_models` is exactly `claude-sonnet-5-5` requests `claude-sonnet-5.5`
- **THEN** the request is refused as not allowed for that key

### Requirement: Claude price lookup matches the same id after prefix, date, and effort decoration

Native Claude price lookup MUST exact-match a price key after removing at most one leading `cc/`, `cp-`, or `cp_` routing prefix. It MUST NOT remove a release date, a reasoning-effort suffix, or a thinking marker, and it MUST NOT map a dotted spelling onto a hyphenated key. A longer id MUST NOT inherit a shorter family's price. A supplied price table that lacks that exact id MUST return no price for that id. An API key whose `allowed_models` names a Claude price key MUST admit that key and the same id with one leading `cc/`, `cp-`, or `cp_` prefix, and MUST NOT admit a longer id, a dotted spelling, or an effort-suffixed spelling.

#### Scenario: A routing prefix uses the existing key

- **WHEN** native price lookup receives `cp-claude-opus-4-7`
- **THEN** it resolves `claude-opus-4-7`

#### Scenario: A dated spelling does not use the undated key

- **WHEN** native price lookup receives `claude-opus-4-5-20251101`
- **THEN** it does not resolve `claude-opus-4-5`

#### Scenario: A longer sibling does not inherit the shorter price

- **WHEN** native price lookup receives `cc/claude-sonnet-5-5`, `claude-sonnet-5-50`, or `not-claude-sonnet-5-5`
- **AND** the supplied price table contains only `claude-sonnet-5`
- **THEN** none of those ids resolve the `claude-sonnet-5` entry

#### Scenario: A family grant rejects a longer lookalike

- **WHEN** an API key whose `allowed_models` is exactly `claude-sonnet-5` requests `claude-sonnet-5-50` or `not-claude-sonnet-5-5`
- **THEN** the request is refused as not allowed for that key

### Requirement: API-key model access does not collapse a separately priced version into its family

`allowed_models` enforcement MUST use authoritative sidecar route resolution, including configured prefix stripping, before canonicalizing both requested and allowed model ids. Once that route has produced the wire id, access MUST NOT remove another leading `cc/`, `cp-`, or `cp_`. Sidecar entry points MUST reject unauthorized routing identities before quota reservation or upstream dispatch. A key whose `allowed_models` names only a model family MUST NOT gain access to a separately routed and separately priced version of that family. A grant of an exact id MUST NOT admit a dotted spelling of that id.

#### Scenario: A second routing prefix stays on the routed id

- **GIVEN** the Claude routing prefix `cp-` strips and `claude-opus-5-5` is a full model
- **WHEN** an API key whose `allowed_models` is exactly `claude-opus-5-5` requests `cp-cp-claude-opus-5-5`
- **THEN** the request is refused as not allowed for that key
- **AND** the same key can still request `cp-claude-opus-5-5`

#### Scenario: A custom stripped prefix cannot bypass the family allowlist

- **GIVEN** the Claude routing prefix is `team.` with stripping enabled
- **WHEN** an API key whose `allowed_models` is exactly `claude-fable-5` requests `team.claude-fable-5-1`
- **THEN** the request is refused before quota reservation or upstream traffic
- **AND** the same key can still request `team.claude-fable-5`
- **AND** a key allowing `claude-fable-5-1` can request `team.claude-fable-5-1`

#### Scenario: A Fable 5 allowlist rejects Fable 5.1

- **WHEN** an API key whose `allowed_models` is exactly `claude-fable-5` requests `cc/claude-fable-5-1`
- **THEN** the request is refused as not allowed for that key

#### Scenario: A Fable 5 allowlist still admits Fable 5

- **WHEN** the same API key requests `cc/claude-fable-5`
- **THEN** the request is allowed

#### Scenario: An allowlist naming the version admits the prefixed id

- **WHEN** an API key whose `allowed_models` is exactly `claude-fable-5-1` requests `cc/claude-fable-5-1`
- **THEN** the request is allowed

#### Scenario: An allowlist naming the version rejects a dotted spelling

- **WHEN** an API key whose `allowed_models` is exactly `claude-fable-5-1` requests `claude-fable-5.1`
- **THEN** the request is refused as not allowed for that key

### Requirement: A preserved full-model id keeps its allowlist identity

When sidecar routing forwards a model id unchanged, API-key access MUST use that id. It MUST NOT remove a leading `cc/`, `cp-`, or `cp_` from an id routing kept. A full-model match MUST use the configured spelling, so a different case of that same id is the same grant. A grant of full model `cp-claude-opus-5-5` MUST NOT admit `claude-opus-5-5` when both are full models on the same integration.

#### Scenario: A preserved prefixed full model rejects the stripped id

- **GIVEN** `cp-claude-opus-5-5` and `claude-opus-5-5` are both CLIProxyAPI full models
- **WHEN** an API key whose `allowed_models` is exactly `cp-claude-opus-5-5` requests `claude-opus-5-5`
- **THEN** the request is refused as not allowed for that key

#### Scenario: A full-model grant admits another case of the same id

- **GIVEN** `cp-claude-sonnet-4-5` is a CLIProxyAPI full model
- **WHEN** an API key whose `allowed_models` is exactly `cp-claude-sonnet-4-5` requests `CP-CLAUDE-SONNET-4-5`
- **THEN** the request is allowed

### Requirement: Claude allowlists ignore pricing aliases

API-key model access MUST treat a Claude id as that exact id after routing, and MUST NOT substitute a pricing alias. A grant of `claude-3-5-sonnet-20241022` MUST NOT admit `claude-3-5-sonnet-latest`. Native price lookup of the older bare name `claude-3-5-sonnet` remains the dated price key.

#### Scenario: A dated Sonnet 3.5 grant rejects the latest spelling

- **WHEN** an API key whose `allowed_models` is exactly `claude-3-5-sonnet-20241022` requests `claude-3-5-sonnet-latest`
- **THEN** the request is refused as not allowed for that key
