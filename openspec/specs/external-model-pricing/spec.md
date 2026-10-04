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

The system MUST resolve prices from authoritative structured provider catalogs or APIs. It MUST NOT declare a per-model price in code, and MUST NOT use an LLM, an agent, or a generalized web search at runtime. The only exception is the dated catalog snapshot defined in "Historical full-input-rate cache-read costs are corrected once". That snapshot reproduces published cards, and only that upgrade uses it.

The published input, cache-read, and output token rates multiplied by the recorded request token usage are the calculated list-price cost. Browser automation MAY be used only as a bounded fallback against a confirmed official model page when no structured endpoint exists.

When the catalog publishes a cache-read rate for the model, cached input tokens MUST be priced at that rate. When it publishes none (the field is absent, `null`, empty, or a negative no-price sentinel), cached input tokens MUST be priced at the full published input rate. The system MUST NOT apply an undocumented cache discount ratio.

A cache-read rate published in a shape the system cannot read MUST NOT be treated as absent. This covers a non-numeric string, a nested object, a boolean, and a non-finite or overflowing number. The entry MUST be treated as unparseable, the same as an unreadable input or output rate, so a parse failure never charges cached input at the input rate.

#### Scenario: A catalog rate produces the recorded cost

- **GIVEN** a catalog publishing $2.00 per 1M input and $4.00 per 1M output for a model
- **AND** a request recording 10 input and 5 output tokens
- **WHEN** the cost is calculated
- **THEN** the recorded cost is exactly `10 * 2.00/1e6 + 5 * 4.00/1e6`

#### Scenario: A published cache-read rate prices cached input

- **GIVEN** a catalog publishing $4.00 per 1M input, $0.20 per 1M cache read, and $20.00 per 1M output for a model
- **AND** a request recording 1,000,000 input tokens, 900,000 of them cached, and 1,000 output tokens
- **WHEN** the cost is calculated
- **THEN** the recorded cost is `100,000 * 4.00/1e6 + 900,000 * 0.20/1e6 + 1,000 * 20.00/1e6`, which is `$0.60`
- **AND** the persisted record carries the `$0.20` cache-read rate

#### Scenario: Without a published cache-read rate cached input costs the input rate

- **GIVEN** a catalog publishing $4.00 per 1M input and $20.00 per 1M output and no cache-read rate for a model
- **AND** a request recording 1,000,000 input tokens, 900,000 of them cached, and 1,000 output tokens
- **WHEN** the cost is calculated
- **THEN** the recorded cost is `$4.02`
- **AND** the persisted record carries no cache-read rate

#### Scenario: An unreadable cache-read rate does not fall back to the input rate

- **GIVEN** a model never priced before
- **AND** a catalog publishing readable input and output rates and an unreadable cache-read rate for it
- **WHEN** the model is resolved
- **THEN** no cost is recorded
- **AND** the record is neither resolved nor not-token-priced
- **AND** the record carries a retry deadline

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

The system MUST persist, per `(serving provider, incoming model id)`: the incoming model id, the canonical catalog model id, the input and output token rates, the cache-read rate when the catalog published one, the catalog source, the retrieval time, and the resolution provenance. Unresolved outcomes MUST be persisted alongside bounded negative-cache and backoff state.

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

The system MUST NOT continuously poll or refresh prices. It MUST provide a separate explicit idempotent maintenance command that runs one pass across persisted mappings, fetches catalogs in bulk where possible, updates changed input, cache-read, and output rates and provenance, preserves prior values on catalog absence, unreadable or unparseable pricing, fetch failure, or durable-store failure, and reports unresolved or ambiguous records. It MUST NOT infer deliberate provider removal from catalog absence. A refresh MUST replace a stored price only with another valid parsed price, except when the record's owning source answers, lists the model, and publishes a recognized no-token-price value; that authoritative same-owner statement MUST transition the record to not-token-priced, clear its rates, and settle it without retry state. No schedule may be added.

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

#### Scenario: A newly published cache-read rate is applied and reported

- **GIVEN** a persisted record with input and output rates and no cache-read rate
- **AND** its owning catalog now publishes a cache-read rate for the model
- **WHEN** the maintenance command runs
- **THEN** the record stores that cache-read rate
- **AND** the pass reports the record as updated and names the new cache-read rate
- **AND** a second pass reports the record unchanged

#### Scenario: A cache-read rate the owning catalog stops publishing is removed

- **GIVEN** a persisted record with input, cache-read, and output rates
- **AND** its owning catalog lists the model with the same input and output rates and no cache-read rate
- **WHEN** the maintenance command runs
- **THEN** the record keeps its input and output rates and no longer carries a cache-read rate
- **AND** the pass reports the record as updated with no cache-read rate published

#### Scenario: An unreadable cache-read rate keeps the stored price

- **GIVEN** a persisted record with input, cache-read, and output rates
- **AND** its owning catalog now publishes the cache-read rate in an unreadable shape
- **WHEN** the maintenance command runs
- **THEN** the record keeps every stored rate
- **AND** the pass reports it as preserved after an unreadable published price

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

### Requirement: Historical full-input-rate cache-read costs are corrected once

The upgrade that adds the stored cache-read rate MUST correct, once, the calculated list prices recorded while cached input was charged at the full input rate.

The migration MUST carry a dated snapshot of the OpenRouter pricing reference's Claude cards: input, cache-read, and output rates as published on 2026-10-03. It MUST seed a record's cache-read rate from that snapshot only when the record is resolved, was priced from the OpenRouter pricing reference, and stores the same input and output rates as the snapshot card for its catalog model. Every other record MUST keep no cache-read rate until the maintenance command refreshes it.

The migration MUST reprice a `catalog_calculated` request log only when its record was seeded and its stored cost equals, within floating-point tolerance, the full-input-rate figure for that record's rates and the row's tokens. The new cost MUST be the published-rate figure. A row with any other stored cost, missing token counts, or any other cost source MUST keep its cost.

Every rollup that already folded a repriced row MUST move by exactly that row's delta:

- The lifetime API-key rollup MUST receive the delta of every repriced non-warmup row at or below `folded_through`, soft-deleted rows included.
- The lifetime account rollup MUST receive it only for the `max(id)` row of each `(account_id, request_id, requested_at)` group, and not for soft-deleted rows.
- The migration MUST set `account_usage_rollup_state.upgrade_repair_from` no later than the hour of the earliest repriced row, so the existing post-upgrade repair refolds hourly and demand buckets from the raw rows. It MUST NOT change `folded_through` or `hourly_folded_through`.

Hourly and demand buckets below the repair's floor cannot be refolded, because retention already removed some or all of their rows. The floor is the earliest surviving request log's time, rounded up to the hour. Such a bucket MUST change only by the deltas of its own surviving repriced rows.

The migration MUST NOT change the cost of a request that retention already removed, in a bucket or in a lifetime total. A bucket records neither which integration served its requests nor how they were priced, so a total that equals the full-input-rate figure can still include upstream-billed or operator-configured costs.

`downgrade()` MUST drop the cache-read column and MUST NOT restore the replaced costs: nothing records them, and they were wrong. Running the upgrade again MUST change no cost and no rollup total. The migration does not correct the running `current_value` of a cost-based API-key limit; that counter restarts at each window reset.

#### Scenario: A full-rate row is repriced and its rollups follow

- **GIVEN** a `catalog_calculated` request log for `cc/claude-opus-5-5`, whose record was resolved from the OpenRouter pricing reference at $4.00 input and $20.00 output per 1M
- **AND** the row records 100,000 input tokens, 90,000 of them cached, 1,000 output tokens, and a stored cost of `$0.42`
- **AND** the lifetime API-key and account rollups already folded it
- **WHEN** the migration runs
- **THEN** the record carries the snapshot's `$0.20` cache-read rate
- **AND** the row's cost is `$0.078`
- **AND** the API-key and account lifetime totals each drop by `$0.342`
- **AND** `upgrade_repair_from` is set no later than the row's hour

#### Scenario: A row that does not prove the full-rate figure keeps its cost

- **GIVEN** request logs whose stored cost is neither the full-rate nor the published-rate figure, that lack output tokens, that were billed upstream or priced from the static table, or whose record's rates match no snapshot card
- **WHEN** the migration runs
- **THEN** each of those rows keeps its cost

#### Scenario: A bucket below the refold floor moves only by its surviving rows

- **GIVEN** an hourly bucket below the refold floor holding three `cc/claude-opus-5-5` requests that retention already removed, whose stored total of `$1.26` equals the full-input-rate figure
- **AND** an hourly bucket below the floor holding four `cc/claude-opus-5` requests charged `$1.05` each, two of which survive as full-rate request logs
- **WHEN** the migration runs
- **THEN** the first bucket keeps `$1.26`
- **AND** the second bucket drops by `$1.62`, the deltas of its two surviving rows
- **AND** the API-key lifetime total moves only by the deltas of repriced surviving rows

#### Scenario: Downgrade keeps corrected costs and a rerun changes nothing

- **GIVEN** the migration has run
- **WHEN** it is downgraded and upgraded again
- **THEN** no request-log cost and no rollup total changes
