## ADDED Requirements

### Requirement: GPT-6 Astra usage cost pricing matches the current published rates

The system MUST recognize `gpt-6-astra` when computing request costs (`cost_usd`). Suffixed aliases such as `gpt-6-astra-2026-09-03` and prefixed ids such as `codex/gpt-6-astra` and `openai/gpt-6-astra` MUST resolve to the canonical `gpt-6-astra` price entry. The system MUST use these USD-per-1M-token rates for input, cached input, and output:

| Model | Standard | Fast/priority | Flex | Standard long context |
| --- | --- | --- | --- | --- |
| `gpt-6-astra` | `10 / 1 / 50` | `20 / 2 / 100` | `5 / 0.50 / 25` | `20 / 2 / 75` |

The existing `priority` and `fast` service-tier aliases MUST use the Fast/priority rates. Standard long-context rates MUST apply only when input tokens exceed 272,000. Flex long-context pricing MUST continue to use the existing Flex short-context rates and multipliers.

#### Scenario: Canonical Astra model resolves pricing

- **WHEN** a request log records model `gpt-6-astra` with token usage
- **THEN** `cost_usd` is computed from the Astra published rates ($10 input / $1 cache-hit / $50 output per 1M tokens)

#### Scenario: Astra standard usage uses the current rate

- **WHEN** a standard-tier `gpt-6-astra` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **THEN** the token cost is `$51.10`

#### Scenario: Astra Fast and Flex usage use their tier rates

- **WHEN** a `gpt-6-astra` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **AND** the request uses `priority` or `fast`
- **THEN** the token cost is `$102.20`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$25.55`

#### Scenario: Astra standard long-context usage uses the current long-context rate

- **WHEN** a standard-tier `gpt-6-astra` request has 300,000 input tokens, 50,000 cached input tokens, and 100,000 output tokens
- **THEN** the token cost is `$12.60`

#### Scenario: Versioned and prefixed aliases use canonical Astra pricing

- **WHEN** the requested model is `gpt-6-astra-2026-09-03`, `codex/gpt-6-astra`, or `openai/gpt-6-astra`
- **THEN** cost accounting resolves it to the `gpt-6-astra` price entry

### Requirement: Historical GPT-6 Astra request logs are backfilled with cost

A database migration MUST recompute `cost_usd` for existing `request_logs` rows whose model is GPT-6 Astra and whose `cost_usd` is NULL, using the recognized Astra pricing, so dollar reports include historical Astra usage.

#### Scenario: Backfill populates cost for prior Astra traffic

- **GIVEN** a pre-existing request log with model `gpt-6-astra`, token usage, and `cost_usd IS NULL`
- **WHEN** the migration runs
- **THEN** the row's `cost_usd` is set from the resolved Astra pricing
- **AND** the row's `cost_source` is `static_table`

#### Scenario: Backfill leaves unknown models as unknown cost

- **GIVEN** a pre-existing request log whose model still has no pricing entry
- **WHEN** the migration runs
- **THEN** that row's `cost_usd` remains NULL

### Requirement: Folded usage rollups receive GPT-6 Astra cost deltas

The backfill migration MUST add newly computed GPT-6 Astra `cost_usd` onto existing usage-rollup rows for request logs already behind `folded_through`, and MUST NOT change `account_usage_rollup_state.folded_through`.

#### Scenario: Backfill adds folded Astra cost into existing usage rollups

- **GIVEN** usage rollups have already folded historical Astra rows while `cost_usd` was NULL
- **WHEN** the migration runs
- **THEN** existing `account_usage_rollups` and `api_key_usage_rollups` rows gain the newly computed Astra `cost_usd` for folded request logs
- **AND** `account_usage_rollup_state.folded_through` is left unchanged
