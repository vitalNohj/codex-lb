## ADDED Requirements

### Requirement: Historical full-input-rate cache-read costs are corrected once

The upgrade that adds the stored cache-read rate MUST correct, once, the calculated list prices recorded while cached input was charged at the full input rate.

The migration MUST carry a dated snapshot of the OpenRouter pricing reference's Claude cards: input, cache-read, and output rates as published on 2026-10-03. It MUST seed a record's cache-read rate from that snapshot only when the record is resolved, was priced from the OpenRouter pricing reference, and stores the same input and output rates as the snapshot card for its catalog model. Every other record MUST keep no cache-read rate until the maintenance command refreshes it.

The migration MUST reprice a `catalog_calculated` request log only when the same run seeded its record and its stored cost equals, within floating-point tolerance, the full-input-rate figure for that record's rates and the row's tokens. The new cost MUST be the published-rate figure. A row with any other stored cost, missing token counts, or any other cost source MUST keep its cost. A cache-read rate a record already holds, from an earlier run or from a price refresh, MUST NOT reprice any row.

Every rollup that already folded a repriced row MUST move by exactly that row's delta:

- The lifetime API-key rollup MUST receive the delta of every repriced non-warmup row at or below `folded_through`, soft-deleted rows included.
- The lifetime account rollup MUST receive it only for the `max(id)` row of each `(account_id, request_id, requested_at)` group, and not for soft-deleted rows.
- The migration MUST set `account_usage_rollup_state.upgrade_repair_from` no later than the hour of the earliest repriced row, so the existing post-upgrade repair refolds hourly and demand buckets from the raw rows. It MUST NOT change `folded_through` or `hourly_folded_through`.

Hourly and demand buckets below the repair's floor cannot be refolded, because retention already removed some or all of their rows. The floor is the earliest surviving request log's time, rounded up to the hour. Such a bucket MUST change only by the deltas of its own surviving repriced rows.

The migration MUST NOT change the cost of a request that retention already removed, in a bucket or in a lifetime total. A bucket records neither which integration served its requests nor how they were priced, so a total that equals the full-input-rate figure can still include upstream-billed or operator-configured costs.

`downgrade()` MUST keep the cache-read column and its rates, because a rate a later refresh wrote cannot be told apart from a seeded one. It MUST NOT restore the replaced costs: nothing records them, and they were wrong. Running the upgrade again MUST change no cost and no rollup total. The migration does not correct the running `current_value` of a cost-based API-key limit; that counter restarts at each window reset.

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
- **AND** every record keeps its cache-read rate

## MODIFIED Requirements

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

### Requirement: Resolution state is persisted durably

The system MUST persist, per `(serving provider, incoming model id)`: the incoming model id, the canonical catalog model id, the input and output token rates, the cache-read rate when the catalog published one, the catalog source, the retrieval time, and the resolution provenance. Unresolved outcomes MUST be persisted alongside bounded negative-cache and backoff state.

#### Scenario: A resolution survives a restart

- **GIVEN** a model id previously resolved to a catalog price
- **WHEN** the process restarts
- **THEN** the request path resolves the same price from persisted state
- **AND** no catalog lookup is performed

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
