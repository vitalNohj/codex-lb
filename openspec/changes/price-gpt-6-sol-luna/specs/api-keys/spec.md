## ADDED Requirements

### Requirement: GPT-6 Sol and Luna native usage cost pricing uses published list rates

When computing native API-key usage, request-log, reservation, or aggregate cost for `gpt-6-sol` or `gpt-6-luna`, the system MUST use these published USD-per-1M-token rates for input, cached input, and output. External integration costs remain governed by `external-model-pricing`, not this native table:

| Model | Standard | Fast/priority | Flex | Standard long context |
| --- | --- | --- | --- | --- |
| `gpt-6-sol` | `2 / 0.20 / 10` | `4 / 0.40 / 20` | `1 / 0.10 / 5` | `4 / 0.40 / 15` |
| `gpt-6-luna` | `0.10 / 0.01 / 0.50` | `0.20 / 0.02 / 1.00` | `0.05 / 0.005 / 0.25` | `0.20 / 0.02 / 0.75` |

The existing `priority` and `fast` service-tier aliases MUST use the Fast/priority rates. Standard long-context rates MUST apply only when input tokens exceed 272,000. Flex long-context pricing MUST continue to use the existing Flex short-context rates and multipliers. Suffixed aliases such as `gpt-6-sol-2026-09-22` and prefixed ids such as `codex/gpt-6-sol` and `openai/gpt-6-luna` MUST resolve to the canonical price entry. Cache-write rates MUST NOT be introduced into this contract.

#### Scenario: Sol standard usage uses the published rate

- **WHEN** a standard-tier `gpt-6-sol` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **THEN** the token cost is `$10.22`

#### Scenario: Sol Fast and Flex usage use their tier rates

- **WHEN** a `gpt-6-sol` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **AND** the request uses `priority` or `fast`
- **THEN** the token cost is `$20.44`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$5.11`

#### Scenario: Sol standard long-context usage uses the long-context rate

- **WHEN** a standard-tier `gpt-6-sol` request has 300,000 input tokens, 50,000 cached input tokens, and 100,000 output tokens
- **THEN** the token cost is `$2.52`

#### Scenario: Luna standard usage uses the published rate

- **WHEN** a standard-tier `gpt-6-luna` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **THEN** the token cost is `$0.511`

#### Scenario: Luna Fast and Flex usage use their tier rates

- **WHEN** a `gpt-6-luna` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **AND** the request uses `priority` or `fast`
- **THEN** the token cost is `$1.022`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$0.2555`

#### Scenario: Luna standard long-context usage uses the long-context rate

- **WHEN** a standard-tier `gpt-6-luna` request has 300,000 input tokens, 50,000 cached input tokens, and 100,000 output tokens
- **THEN** the token cost is `$0.126`

#### Scenario: Versioned and prefixed aliases use canonical Sol and Luna pricing

- **WHEN** the requested model is `gpt-6-sol-2026-09-22`, `codex/gpt-6-sol`, `openai/gpt-6-luna`, or `gpt-6-luna-20260922`
- **THEN** cost accounting resolves it to the matching `gpt-6-sol` or `gpt-6-luna` price entry

#### Scenario: Lookalike ids do not receive Sol or Luna pricing

- **WHEN** cost accounting receives model `gpt-6-sol-pro` or `unrelated/gpt-6-luna`
- **THEN** it does not resolve a `gpt-6-sol` or `gpt-6-luna` price

### Requirement: GPT-6 Sol and Luna grants stay bounded to their model ids

An `allowed_models` entry of `gpt-6-sol` or `gpt-6-luna` MUST admit the canonical id, a dated snapshot of that id, and the same id with a `codex/` or `openai/` prefix. It MUST NOT admit an id that only contains the name, such as `gpt-6-sol-pro` or `unrelated/gpt-6-luna`.

#### Scenario: A Sol grant admits supported id forms

- **WHEN** an API key allows `gpt-6-sol`
- **AND** the request model is `gpt-6-sol`, `gpt-6-sol-2026-09-22`, `codex/gpt-6-sol`, or `openai/gpt-6-sol`
- **THEN** model access allows the request

#### Scenario: A Sol grant rejects lookalike ids

- **WHEN** an API key allows `gpt-6-sol`
- **AND** the request model is `gpt-6-sol-pro` or `unrelated/gpt-6-sol`
- **THEN** model access rejects the request

#### Scenario: A Luna grant rejects lookalike ids

- **WHEN** an API key allows `gpt-6-luna`
- **AND** the request model is `gpt-6-luna-pro` or `unrelated/gpt-6-luna`
- **THEN** model access rejects the request

### Requirement: Historical GPT-6 Sol and Luna request logs are backfilled with cost

A database migration MUST recompute `cost_usd` for existing `request_logs` rows whose model is GPT-6 Sol or GPT-6 Luna and whose `cost_usd` is NULL, using the recognized pricing, so dollar reports include that historical usage.

#### Scenario: Backfill populates cost for prior Sol and Luna traffic

- **GIVEN** a pre-existing request log with model `gpt-6-sol` or `gpt-6-luna`, token usage, and `cost_usd IS NULL`
- **WHEN** the migration runs
- **THEN** the row's `cost_usd` is set from the resolved pricing
- **AND** the row's `cost_source` is `static_table`

#### Scenario: Backfill leaves unknown models as unknown cost

- **GIVEN** a pre-existing request log whose model still has no pricing entry
- **WHEN** the migration runs
- **THEN** that row's `cost_usd` remains NULL

#### Scenario: Backfill does not price lookalike model ids

- **GIVEN** a pre-existing request log with model `gpt-6-sol-pro` or `unrelated/gpt-6-luna` and `cost_usd IS NULL`
- **WHEN** the migration runs
- **THEN** that row's `cost_usd` remains NULL

#### Scenario: Backfill leaves externally owned prices alone

- **GIVEN** a GPT-6 Sol or GPT-6 Luna request log whose `price_status` is set, or whose `cost_source` is a value other than `static_table`
- **WHEN** the migration runs
- **THEN** that row's `cost_usd`, `cost_source`, and `price_status` are unchanged, including when its `cost_usd` is NULL

#### Scenario: Backfill leaves already-priced rows alone

- **GIVEN** a GPT-6 Sol or GPT-6 Luna request log that already has a non-NULL `cost_usd`
- **WHEN** the migration runs
- **THEN** that row's `cost_usd` and `cost_source` are unchanged

#### Scenario: Rollback does not blank costs the migration never wrote

- **GIVEN** the migration has run and both migration-written and request-path-written costs exist
- **WHEN** the migration is downgraded
- **THEN** no `cost_usd` or `cost_source` value is cleared and no usage-rollup total changes

### Requirement: Folded usage rollups receive GPT-6 Sol and Luna cost deltas

The backfill migration MUST add newly computed `cost_usd` onto existing usage-rollup rows for request logs already behind `folded_through`, and MUST NOT change `account_usage_rollup_state.folded_through`.

#### Scenario: Backfill adds folded cost into existing usage rollups

- **GIVEN** usage rollups have already folded historical Sol or Luna rows while `cost_usd` was NULL
- **WHEN** the migration runs
- **THEN** existing `account_usage_rollups` and `api_key_usage_rollups` rows gain the newly computed `cost_usd` for folded request logs
- **AND** `account_usage_rollup_state.folded_through` is left unchanged

#### Scenario: Duplicate request rows are not counted twice in the account rollup

- **GIVEN** two folded request logs share one `(account_id, request_id, requested_at)` group, the higher-id row already priced and the lower-id row NULL
- **WHEN** the migration runs and reprices the lower-id row
- **THEN** `account_usage_rollups` gains no cost for that group, because the deduplicating account reader folds only the group's `max(id)` row
- **AND** `api_key_usage_rollups`, which does not deduplicate, gains the repriced row's cost

#### Scenario: Hourly cost buckets are repaired for the repriced range

- **GIVEN** rows repriced by the migration fall below `account_usage_rollup_state.hourly_folded_through`
- **WHEN** the migration runs
- **THEN** `account_usage_rollup_state.upgrade_repair_from` is set no later than the earliest repriced hour
- **AND** `hourly_folded_through` and `folded_through` are left unchanged
