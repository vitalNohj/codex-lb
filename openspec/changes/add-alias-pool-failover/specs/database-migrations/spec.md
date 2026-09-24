## ADDED Requirements

### Requirement: Alias pool migration normalizes alias values and adds pool log columns

Alembic MUST ship one revision, parented on the live head
`20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads`, that:

- rewrites every string value in `dashboard_settings.model_aliases_json` to a
  one-element pool `{"targets": [value]}`, leaving values that are already pool
  objects untouched and dropping entries that are neither;
- adds `request_logs.upstream_model` (String, nullable) and
  `request_logs.pool_attempts` (Integer, nullable), adding each column only when
  missing.

Downgrade MUST NOT discard targets: while any alias has more than one target it
MUST fail before changing anything, naming those aliases and how to reduce
them. Otherwise it MUST rewrite each one-target pool back to its target as a
string and MUST drop only the two new request-log columns. Settings rows MUST
be read and rewritten in bounded batches. The upgrade MUST be idempotent:
running it against a row that already holds the pool shape MUST leave that row
byte-for-byte unchanged. The column `model_aliases_json` itself MUST NOT be
renamed or retyped.

#### Scenario: Legacy alias strings become one-element pools

- **GIVEN** `model_aliases_json` is `{"custom_r1": "cc/claude-opus-4-8"}`
- **WHEN** the migration upgrades
- **THEN** `model_aliases_json` is `{"custom_r1": {"targets": ["cc/claude-opus-4-8"]}}`

#### Scenario: Upgrade is idempotent on pool-shaped rows

- **GIVEN** `model_aliases_json` already holds `{"a": {"targets": ["x", "y"]}}`
- **WHEN** the migration upgrades
- **THEN** the value is unchanged

#### Scenario: Downgrade refuses while an alias has fallback targets

- **GIVEN** `model_aliases_json` is `{"a": {"targets": ["x", "y"]}}`
- **WHEN** the migration downgrades
- **THEN** the downgrade fails with an error naming alias `a`
- **AND** `model_aliases_json` and the `request_logs` columns are unchanged

#### Scenario: Downgrade restores the legacy shape

- **GIVEN** `model_aliases_json` is `{"a": {"targets": ["x"]}}`
- **WHEN** the migration downgrades
- **THEN** `model_aliases_json` is `{"a": "x"}`
- **AND** `request_logs` no longer has `upstream_model` or `pool_attempts`

#### Scenario: Migration check reports a single head

- **WHEN** the Alembic migration check runs on a database at the live head
- **THEN** the check passes without `MultipleHeads`
