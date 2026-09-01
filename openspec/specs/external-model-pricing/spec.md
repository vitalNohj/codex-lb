# external-model-pricing Specification

## Purpose
Define one shared, persistent model-price resolver for external integrations (OpenRouter, OrcaRouter, CLIProxyAPI), and how the calculated list-price cost it produces is kept distinct from an upstream-reported billed amount.

## Requirements

### Requirement: Participating integrations are a closed set

External model price resolution MUST apply to OpenRouter, OrcaRouter, and CLIProxyAPI only. Ollama and OmniRoute MUST NOT participate: their request-log cost stays `--` and their rows carry no price status.

#### Scenario: An excluded integration produces no pricing record

- **GIVEN** a request served by Ollama or OmniRoute
- **WHEN** the request log is written
- **THEN** no `external_model_prices` row is created
- **AND** the row's price status is NULL
- **AND** the request-log UI renders `--` with no unresolved marker

### Requirement: Prices come from authoritative structured catalogs

The system MUST resolve prices from authoritative structured provider catalogs or APIs. It MUST NOT declare a per-model price in code, and MUST NOT use an LLM, an agent, or a generalized web search at runtime.

A published input/output token rate multiplied by recorded request token usage is the calculated list-price cost. Browser automation MAY be used only as a bounded fallback against a confirmed official model page when no structured endpoint exists.

Cached input tokens MUST be priced at the full published input rate. The system MUST NOT apply an undocumented cache discount ratio.

#### Scenario: A catalog rate produces the recorded cost

- **GIVEN** a catalog publishing $2.00 per 1M input and $4.00 per 1M output for a model
- **AND** a request recording 10 input and 5 output tokens
- **WHEN** the cost is calculated
- **THEN** the recorded cost is exactly `10 * 2.00/1e6 + 5 * 4.00/1e6`

### Requirement: Actual billed cost and calculated list price stay distinct

An amount the serving integration reports as its own billed figure is authoritative actual spend. It MUST be stored verbatim, MUST NOT be overwritten by a calculated figure, and MUST NOT be recomputed or reconciled against list pricing.

A calculated list-price cost MUST be recorded only when no upstream-billed amount was reported, and MUST be marked with its own provenance. The distinction MUST be preserved in the data model and surfaced in the UI wherever it matters. Calculated external-integration costs MUST be included in cost totals.

#### Scenario: An upstream-billed amount survives a resolved catalog price

- **GIVEN** a model with a resolved catalog price
- **AND** an upstream response reporting a billed amount
- **WHEN** the request log is written
- **THEN** the stored cost equals the upstream-reported amount
- **AND** its provenance is recorded as upstream-billed

#### Scenario: A calculated cost is labelled as list price

- **GIVEN** a model with a resolved catalog price
- **AND** an upstream response reporting no billed amount
- **WHEN** the request log is written
- **THEN** the stored cost is the catalog-calculated figure
- **AND** its provenance is recorded as catalog-calculated
- **AND** the UI explains that the figure is list price and may differ from the actual debit

### Requirement: Resolution state is persisted durably

The system MUST persist, per `(serving provider, incoming model id)`: the incoming model id, the canonical catalog model id, the input and output token rates, the catalog source, the retrieval time, and the resolution provenance. Unresolved outcomes MUST be persisted alongside bounded negative-cache and backoff state.

#### Scenario: A resolution survives a restart

- **GIVEN** a model id previously resolved to a catalog price
- **WHEN** the process restarts
- **THEN** the request path resolves the same price from persisted state
- **AND** no catalog lookup is performed

### Requirement: The request path is cache-first and idempotent

A known, successfully priced incoming model id MUST cause no network lookup, no browser work, no model search, no catalog scan, and no record rewrite on the request path. The request MUST NOT wait for remote work.

#### Scenario: Repeated traffic to a priced model does no work

- **GIVEN** a model id with a persisted resolved price
- **WHEN** many requests use that model id
- **THEN** no catalog lookup is dispatched
- **AND** the persisted record is not rewritten

### Requirement: Lookups are deduplicated and bounded

Only a previously unseen eligible model id, or a known id whose prior lookup is explicitly unresolved and whose retry window is due, MAY enqueue a lookup. Concurrent first sightings of the same id MUST collapse into one deduplicated bounded job. Persisted unresolved results and backoff state MUST prevent traffic from causing repeated lookup work.

#### Scenario: Concurrent first sightings run one lookup

- **GIVEN** a model id never seen for a provider
- **WHEN** many concurrent requests use that id before the lookup completes
- **THEN** exactly one lookup job runs
- **AND** exactly one record is written

#### Scenario: An unresolved model is not retried until its window is due

- **GIVEN** a model id whose lookup produced no price
- **WHEN** further requests use that id before its retry deadline
- **THEN** no additional lookup is dispatched

### Requirement: Resolution follows configured routing before catalog matching

Resolution MUST first honor operator-configured routing prefixes and explicit aliases. A CLIProxyAPI id such as `cc/claude-fable-5` MUST be mapped to its actual provider/catalog identity rather than by blind prefix removal. The serving provider's own catalog MUST be queried before OpenRouter's structured catalog, which serves as the broad pricing fallback.

#### Scenario: A prefixed id resolves through its configured prefix

- **GIVEN** an operator-configured strip-enabled prefix `cc/`
- **AND** a catalog listing `anthropic/claude-fable-5`
- **WHEN** `cc/claude-fable-5` is resolved
- **THEN** the canonical catalog model is `anthropic/claude-fable-5`

#### Scenario: The serving catalog wins for a shared model id

- **GIVEN** two catalogs listing the same model id at different rates
- **WHEN** a request served by the first provider is priced
- **THEN** the first provider's own published rate is used

#### Scenario: A dated vendor release resolves to its canonical catalog entry

- **GIVEN** a catalog listing `anthropic/claude-sonnet-4.5`
- **WHEN** `claude-sonnet-4-5-20250929` is resolved
- **THEN** the canonical catalog model is `anthropic/claude-sonnet-4.5`
- **AND** the same holds through a configured strip-enabled prefix such as `cc/`

#### Scenario: A shortened dated id that matches two catalog models abstains

- **GIVEN** a catalog listing one bare name under two vendors at different rates
- **WHEN** the dated form of that name is resolved
- **THEN** the outcome is ambiguous and no price is recorded

### Requirement: Unsafe substring-glob pricing is retired for these paths

The system MUST NOT price an external-integration model by matching the model name against a substring or glob pattern. Punctuation-only spelling differences MUST resolve to the same catalog entry. A variant suffix, a vendor prefix, or any other name extension MUST NOT inherit a shorter entry's price.

A trailing `-YYYYMMDD` release stamp is the sole exception, because it names a release of one model rather than a second model. It MUST be recognised only in that exact shape, only when the digits form a real calendar date, and the shortened id MUST re-enter resolution from the top so it still abstains on ambiguity. Any other trailing segment MUST NOT be removed.

#### Scenario: Punctuation variants share one price

- **GIVEN** a catalog entry for `anthropic/claude-opus-4.5`
- **WHEN** `anthropic/claude-opus-4-5` is resolved
- **THEN** it resolves to that same entry and rate

#### Scenario: A name extension does not inherit a shorter entry's rate

- **GIVEN** a catalog entry for `meta-llama/llama-3.1-8b-instruct`
- **WHEN** `aion-labs/aion-rp-llama-3.1-8b` is resolved
- **THEN** the outcome is unresolved
- **AND** no price is recorded

### Requirement: Ambiguity abstains

When more than one catalog model plausibly matches an incoming id, the system MUST abstain and record no price. An eligible but unresolved model MUST remain allowed and token-counted. Token-based quota enforcement MUST continue normally, while cost-based quota enforcement MUST accrue no cost for that request because no trustworthy amount exists.

#### Scenario: Two vendors publishing one bare name abstains

- **GIVEN** a catalog listing the same bare model name under two vendors at different rates
- **WHEN** that bare name is resolved
- **THEN** the outcome is ambiguous
- **AND** no price is recorded
- **AND** the competing candidates are recorded for operator review

#### Scenario: An unresolved model is still served

- **GIVEN** an eligible model whose price is unresolved
- **WHEN** a request uses that model
- **THEN** the request is served and logged as before
- **AND** allow-list and token-based quota behavior is unchanged
- **AND** cost-based quota enforcement accrues no cost for the request

### Requirement: A model without published token rates is a settled outcome

A model an authoritative catalog lists without per-token rates (per-request, per-second, per-minute, or router models) MUST be recorded as not token priced, MUST NOT carry retry state, and MUST render as `--` rather than as an unresolved marker.

#### Scenario: A router model settles without retry state

- **GIVEN** a catalog listing a router model with no per-token rate
- **WHEN** the model is resolved
- **THEN** the record's status is not-token-priced
- **AND** it carries no retry deadline
- **AND** later requests dispatch no further lookup

### Requirement: OpenRouter is a pricing reference, not an availability authority

The system MUST NOT infer model availability, addition, or removal from a model's presence in or absence from OpenRouter. Serving integrations continue to own discovery and routing state.

#### Scenario: OpenRouter absence does not affect routing

- **GIVEN** a model absent from OpenRouter's catalog
- **WHEN** price resolution completes
- **THEN** the serving integration's discovery and routing state is unchanged

### Requirement: Refresh is an explicit maintenance command, never a schedule

The system MUST NOT continuously poll or refresh prices. It MUST provide a separate explicit idempotent maintenance command that runs one pass across persisted mappings, fetches catalogs in bulk where possible, updates changed rates and provenance, preserves prior values on catalog absence, unreadable or unparseable pricing, fetch failure, or durable-store failure, and reports unresolved or ambiguous records. It MUST NOT infer deliberate provider removal from catalog absence. A refresh MUST replace a stored price only with another valid parsed price, except when the record's owning source answers, lists the model, and publishes a recognized no-token-price value; that authoritative same-owner statement MUST transition the record to not-token-priced, clear its rates, and settle it without retry state. No schedule may be added.

#### Scenario: A pass over unchanged catalogs changes nothing

- **GIVEN** persisted records matching the current catalogs
- **WHEN** the maintenance command runs twice
- **THEN** both passes report no rate changes

#### Scenario: A source failure preserves prior values

- **GIVEN** a persisted record with a known rate
- **AND** every catalog source that record depends on is unreachable
- **WHEN** the maintenance command runs
- **THEN** the record keeps its prior rate and provenance
- **AND** the report names the unavailable source

#### Scenario: A source that did not answer keeps ownership of its rate

- **GIVEN** a persisted record supplied by the serving provider's own catalog
- **AND** that catalog is unreachable or the integration is switched off
- **AND** the pricing reference is reachable and lists the same id at a different rate
- **WHEN** the maintenance command runs
- **THEN** the record keeps the serving provider's rate and provenance
- **AND** the pass reports it as preserved rather than updated

#### Scenario: A stored price survives a missing catalog entry

- **GIVEN** a persisted record with a known rate
- **AND** its serving catalog is reachable and no longer lists the model
- **WHEN** the maintenance command runs
- **THEN** the record keeps its prior rate and provenance
- **AND** the report identifies that no valid replacement was applied

#### Scenario: A refresh only applies a valid parsed replacement

- **GIVEN** a persisted record with a known rate
- **AND** a refresh returns a valid parsed rate from the record's trustworthy catalog source
- **WHEN** the maintenance command runs
- **THEN** the new rate and provenance replace the prior values

#### Scenario: An owning source authoritatively declares no token price

- **GIVEN** a persisted priced record owned by a catalog source
- **AND** that source answers, lists the model, and publishes a recognized no-token-price value
- **WHEN** the maintenance command runs
- **THEN** the record becomes not-token-priced
- **AND** its input and output rates are cleared
- **AND** its retry state is cleared
- **AND** the request-log cost marker is `--` rather than `!!`

#### Scenario: A failed refresh cannot weaken a stored price

- **GIVEN** a persisted record with a known rate
- **AND** a refresh encounters a catalog outage, missing entry, unreadable or unparseable entry, or durable-store failure
- **WHEN** the maintenance command runs
- **THEN** the record keeps its prior rate, ownership, and provenance unchanged

### Requirement: Request logs mark eligible models that stay unresolved

The request-log UI MUST show `!!` with an explanatory tooltip for an OpenRouter, OrcaRouter, or CLIProxyAPI model that should be token-priceable but remains unresolved after lookup. It MUST keep `--` for Ollama, OmniRoute, missing token usage, and genuinely non-token-priced or router cases.

#### Scenario: An unresolved eligible model is marked

- **GIVEN** a request log row for a participating integration whose price status is unresolved or ambiguous
- **WHEN** the request log is rendered
- **THEN** the cost cell shows `!!`
- **AND** its tooltip explains why no price was recorded

#### Scenario: Missing token usage is not marked

- **GIVEN** a request log row whose model has a resolved price but reported no token usage
- **WHEN** the request log is rendered
- **THEN** the cost cell shows `--` with no unresolved marker

### Requirement: Account-drain semantics are not expanded

Account-drain semantics remain limited to Codex/ChatGPT account drain and existing CLIProxyAPI per-account token attribution. OpenRouter and OrcaRouter list-price calculations MUST NOT fabricate account-drain values.

#### Scenario: A list-price calculation drains no account

- **GIVEN** an OpenRouter or OrcaRouter request priced from a catalog rate
- **WHEN** the request log is written
- **THEN** no account-drain value is recorded for it
