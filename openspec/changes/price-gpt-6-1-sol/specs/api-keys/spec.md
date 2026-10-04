## ADDED Requirements

### Requirement: GPT-6.1 Sol native usage cost pricing uses published list rates

When computing native API-key usage, request-log, reservation, or aggregate cost for `gpt-6.1-sol`, the system MUST use these published USD-per-1M-token rates for input, cached input, and output. External integration costs remain governed by `external-model-pricing`, not this native table:

| Model | Standard | Fast/priority | Flex | Standard long context |
| --- | --- | --- | --- | --- |
| `gpt-6.1-sol` | `2 / 0.10 / 10` | `4 / 0.20 / 20` | `1 / 0.05 / 5` | `4 / 0.20 / 15` |

The existing `priority` and `fast` service-tier aliases MUST use the Fast/priority rates. Standard long-context rates MUST apply only when input tokens exceed 272,000. Flex long-context pricing MUST continue to use the existing Flex short-context rates and multipliers. Dated snapshots such as `gpt-6.1-sol-2026-10-01` and `gpt-6.1-sol-20261001`, the `codex/` and `openai/` prefixes, and one leading `cc/`, `cp-`, or `cp_` prefix on the exact id MUST resolve to this entry regardless of letter case. `gpt-6.1-sol` MUST NOT resolve to the `gpt-6-sol` price, and `gpt-6-sol` MUST NOT resolve to the `gpt-6.1-sol` price. Cache-write rates MUST NOT be introduced into this contract.

#### Scenario: GPT-6.1 Sol standard usage uses the published rate

- **WHEN** a standard-tier `gpt-6.1-sol` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **THEN** the token cost is `$10.21`

#### Scenario: GPT-6.1 Sol Fast and Flex usage use their tier rates

- **WHEN** a `gpt-6.1-sol` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **AND** the request uses `priority` or `fast`
- **THEN** the token cost is `$20.42`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$5.105`

#### Scenario: GPT-6.1 Sol long-context usage uses the long-context rate

- **WHEN** a standard-tier `gpt-6.1-sol` request has 300,000 input tokens, 50,000 cached input tokens, and 100,000 output tokens
- **THEN** the token cost is `$2.51`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$1.255`

#### Scenario: GPT-6.1 Sol keeps its own cache-read rate

- **WHEN** a standard-tier `gpt-6-sol` request and a standard-tier `gpt-6.1-sol` request each have 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **THEN** the `gpt-6-sol` cost is `$10.22`
- **AND** the `gpt-6.1-sol` cost is `$10.21`

#### Scenario: Versioned and prefixed ids use the GPT-6.1 Sol price

- **WHEN** the requested model is `gpt-6.1-sol-2026-10-01`, `GPT-6.1-SOL-20261001`, `codex/gpt-6.1-sol`, `openai/gpt-6.1-sol`, or `cc/gpt-6.1-sol`
- **THEN** cost accounting resolves it to the `gpt-6.1-sol` price entry

#### Scenario: Lookalike ids do not receive the GPT-6.1 Sol price

- **WHEN** cost accounting receives model `gpt-6.1-sol-pro`, `gpt-6.1-sol-high`, or `unrelated/gpt-6.1-sol`
- **THEN** it does not resolve a `gpt-6.1-sol` price

### Requirement: GPT-6.1 Sol grants stay bounded to its model id

An `allowed_models` entry of `gpt-6.1-sol` MUST admit the canonical id, a dated snapshot of that id, and the same id with a `codex/` or `openai/` prefix. It MUST NOT admit an id that only contains the name, such as `gpt-6.1-sol-pro` or `unrelated/gpt-6.1-sol`. A `gpt-6.1-sol` grant MUST NOT admit `gpt-6-sol`, and a `gpt-6-sol` grant MUST NOT admit `gpt-6.1-sol`.

#### Scenario: A GPT-6.1 Sol grant admits supported id forms

- **WHEN** an API key allows `gpt-6.1-sol`
- **AND** the request model is `gpt-6.1-sol`, `gpt-6.1-sol-2026-10-01`, `codex/gpt-6.1-sol`, or `openai/gpt-6.1-sol`
- **THEN** model access allows the request

#### Scenario: A GPT-6.1 Sol grant rejects lookalike ids

- **WHEN** an API key allows `gpt-6.1-sol`
- **AND** the request model is `gpt-6.1-sol-pro` or `unrelated/gpt-6.1-sol`
- **THEN** model access rejects the request

#### Scenario: GPT-6 Sol and GPT-6.1 Sol grants do not admit each other

- **WHEN** an API key allows only `gpt-6-sol`
- **AND** the request model is `gpt-6.1-sol`
- **THEN** model access rejects the request
- **WHEN** an API key allows only `gpt-6.1-sol`
- **AND** the request model is `gpt-6-sol`
- **THEN** model access rejects the request

### Requirement: Historical GPT-6.1 Sol request logs are backfilled with cost

A database migration MUST set `cost_usd` on existing `request_logs` rows whose model resolves to the `gpt-6.1-sol` price and whose `cost_usd` is NULL, so dollar reports include that usage. Each row MUST be priced at the rates above for its own service tier and token counts, and its `cost_source` MUST become `static_table`. The migration MUST carry its own copy of those rates and of the id rule, so a later edit to the live price table cannot change what it writes.

The migration MUST leave unchanged: rows of lookalike ids, rows missing the token counts a price needs (input, and output or reasoning), rows whose writer already settled the price (any `price_status`, or a `cost_source` other than `static_table`), and rows that already have a `cost_usd`. Downgrading MUST NOT clear any cost, and running the upgrade again MUST change nothing.

#### Scenario: Backfill prices prior GPT-6.1 Sol traffic

- **GIVEN** pre-existing request logs with model `gpt-6.1-sol`, `GPT-6.1-SOL-20261001`, `openai/gpt-6.1-sol`, or `cc/gpt-6.1-sol`, token usage, and `cost_usd IS NULL`
- **WHEN** the migration runs
- **THEN** each row's `cost_usd` is the published-rate cost of its service tier and tokens
- **AND** each row's `cost_source` is `static_table`

#### Scenario: Backfill does not price lookalike model ids

- **GIVEN** a pre-existing request log with model `gpt-6.1-sol-pro` or `unrelated/gpt-6.1-sol` and `cost_usd IS NULL`
- **WHEN** the migration runs
- **THEN** that row's `cost_usd` remains NULL

#### Scenario: Backfill leaves settled and already-priced rows alone

- **GIVEN** a GPT-6.1 Sol request log whose `price_status` is set, whose `cost_source` is a value other than `static_table`, whose input token count is missing, or whose `cost_usd` is already set
- **WHEN** the migration runs
- **THEN** that row's `cost_usd`, `cost_source`, and `price_status` are unchanged

#### Scenario: Rollback and rerun leave the backfilled costs in place

- **GIVEN** the migration has run
- **WHEN** it is downgraded and then upgraded again
- **THEN** no `cost_usd` or `cost_source` value and no usage-rollup total changes

### Requirement: Usage rollups that folded GPT-6.1 Sol logs gain the backfilled cost

The GPT-6.1 Sol backfill MUST move every usage rollup that already folded a repriced row by exactly that row's new cost, as the fold would have counted it. It MUST NOT change `folded_through` or `hourly_folded_through`.

- `account_usage_rollups` and `api_key_usage_rollups` MUST gain the cost of repriced rows at or before `folded_through`. Neither counts `warmup` or `limit_warmup` rows. The API-key rollup counts every other row, soft-deleted included. The account rollup counts a row only when it is not soft-deleted and has the highest id of its `(account_id, request_id, requested_at)` group.
- Hourly and demand buckets that the surviving raw rows can rebuild MUST be repaired by setting `upgrade_repair_from` no later than the earliest repriced hour below `hourly_folded_through`. An earlier marker MUST be kept.
- The repair cannot rebuild an hour that starts before the earliest surviving request log. A repriced row below both that first rebuildable hour and `hourly_folded_through` MUST add its cost to its hourly bucket's `cost_usd`, one to that bucket's `cost_count`, and its cost to its demand slot's `cost_usd`.

#### Scenario: Lifetime rollups gain the folded backfilled cost

- **GIVEN** usage rollups folded GPT-6.1 Sol rows while their `cost_usd` was NULL
- **WHEN** the migration runs
- **THEN** `account_usage_rollups` and `api_key_usage_rollups` gain the newly computed cost of the folded rows
- **AND** `account_usage_rollup_state.folded_through` is unchanged

#### Scenario: Duplicate request rows are counted once in the account rollup

- **GIVEN** two folded NULL-cost GPT-6.1 Sol request logs share one `(account_id, request_id, requested_at)` group
- **WHEN** the migration prices both rows
- **THEN** `account_usage_rollups` gains only the higher-id row's cost
- **AND** `api_key_usage_rollups` gains both rows' cost

#### Scenario: Rebuildable hourly buckets are left to the repair

- **GIVEN** repriced rows below `hourly_folded_through` in hours the surviving raw rows fully cover
- **WHEN** the migration runs
- **THEN** `upgrade_repair_from` is set no later than the earliest repriced hour
- **AND** `hourly_folded_through` is unchanged

#### Scenario: Buckets the repair cannot rebuild gain the cost directly

- **GIVEN** a repriced row folded into an hour that starts before the earliest surviving request log
- **WHEN** the migration runs
- **THEN** that hourly bucket's `cost_usd` gains the row's cost and its `cost_count` gains one
- **AND** the row's demand slot's `cost_usd` gains the row's cost
