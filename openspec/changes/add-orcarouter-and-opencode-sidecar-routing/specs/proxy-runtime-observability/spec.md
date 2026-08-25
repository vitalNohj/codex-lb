## ADDED Requirements

### Requirement: Record OrcaRouter sidecar observability as normal HTTP traffic

Request logs MUST record OrcaRouter sidecar rows with normal HTTP presentation and provider label `OrcaRouter`. OrcaRouter rows MUST use `source = "orcarouter_sidecar"`, MUST preserve the effective client model in log fields, MUST display transport as `HTTP`, and MUST NOT show a generic sidecar badge in the model column.

When OrcaRouter responses provide token counts, request logs MUST record those usage counters. Request logs MUST keep `cost` null unless existing pricing data supports a real cost calculation; missing OrcaRouter pricing MUST NOT be converted to zero.

#### Scenario: OrcaRouter request log row is understandable

- **GIVEN** an OrcaRouter sidecar request succeeds
- **WHEN** an authenticated operator views Request Logs
- **THEN** the row shows transport `HTTP`
- **AND** the account/provider column shows `OrcaRouter`
- **AND** the model column does not show a sidecar badge

#### Scenario: OrcaRouter usage is recorded without invented cost

- **GIVEN** an OrcaRouter response includes prompt and completion token counts
- **AND** no authoritative OrcaRouter pricing entry exists for that model
- **WHEN** the request log row is written
- **THEN** input and output tokens are recorded from the upstream usage
- **AND** `cost` is null

#### Scenario: Synthetic OrcaRouter account appears

- **GIVEN** OrcaRouter sidecar settings are configured or enabled
- **WHEN** an authenticated operator calls the Accounts API
- **THEN** the response includes a read-only synthetic account with display name `OrcaRouter`
- **AND** the account includes health status, base URL, model count, last checked time, and request usage derived from OrcaRouter sidecar request logs

### Requirement: Record OpenCode Zen sidecar observability as normal HTTP traffic

Request logs MUST record OpenCode Zen sidecar rows with normal HTTP presentation and provider label `OpenCode Zen`. OpenCode Zen rows MUST use `source = "opencode_zen_sidecar"`, MUST preserve the effective client model in log fields, MUST display transport as `HTTP`, and MUST NOT show a generic sidecar badge in the model column.

OpenCode Zen models that match existing free-model detection (`-free` suffix or opaque allowlist such as `opencode-zen/big-pickle`) MUST record cost as zero. Paid-looking OpenCode Zen models without pricing MUST keep `cost` null rather than inventing zero.

#### Scenario: OpenCode Zen request log row is understandable

- **GIVEN** an OpenCode Zen sidecar request succeeds
- **WHEN** an authenticated operator views Request Logs
- **THEN** the row shows transport `HTTP`
- **AND** the account/provider column shows `OpenCode Zen`
- **AND** the model column does not show a sidecar badge

#### Scenario: Suffixed free OpenCode Zen model records zero cost

- **GIVEN** an OpenCode Zen sidecar request succeeds for effective model `opencode-zen/mimo-v2.5-free`
- **WHEN** the request log row is written
- **THEN** `cost` is `0`

#### Scenario: Opaque free OpenCode Zen model records zero cost

- **GIVEN** an OpenCode Zen sidecar request succeeds for effective model `opencode-zen/big-pickle`
- **WHEN** the request log row is written
- **THEN** `cost` is `0`

#### Scenario: Synthetic OpenCode Zen account appears

- **GIVEN** OpenCode Zen sidecar settings are configured or enabled
- **WHEN** an authenticated operator calls the Accounts API
- **THEN** the response includes a read-only synthetic account with display name `OpenCode Zen`
- **AND** the account includes health status, base URL, model count, last checked time, and request usage derived from OpenCode Zen sidecar request logs
- **AND** the account is not treated as configured/active unless a stored API key is present

### Requirement: Record OpenCode Free sidecar observability as normal HTTP traffic

Request logs MUST record OpenCode Free sidecar rows with normal HTTP presentation and provider label `OpenCode Free`. OpenCode Free rows MUST use `source = "opencode_sidecar"`, MUST preserve the effective client model in log fields, MUST display transport as `HTTP`, and MUST NOT show a generic sidecar badge in the model column.

OpenCode Free models that match existing free-model detection (`-free` suffix or opaque allowlist such as `oc/big-pickle`) MUST record cost as zero. Paid-looking OpenCode Free models without pricing MUST keep `cost` null rather than inventing zero.

#### Scenario: OpenCode Free request log row is understandable

- **GIVEN** an OpenCode Free sidecar request succeeds
- **WHEN** an authenticated operator views Request Logs
- **THEN** the row shows transport `HTTP`
- **AND** the account/provider column shows `OpenCode Free`
- **AND** the model column does not show a sidecar badge

#### Scenario: Opaque free OpenCode model records zero cost

- **GIVEN** an OpenCode Free sidecar request succeeds for effective model `oc/big-pickle`
- **WHEN** the request log row is written
- **THEN** `cost` is `0`

#### Scenario: Suffixed free OpenCode model records zero cost

- **GIVEN** an OpenCode Free sidecar request succeeds for effective model `oc/deepseek-v4-flash-free`
- **WHEN** the request log row is written
- **THEN** `cost` is `0`

#### Scenario: Synthetic OpenCode Free account appears

- **GIVEN** the OpenCode Free sidecar is enabled
- **WHEN** an authenticated operator calls the Accounts API
- **THEN** the response includes a read-only synthetic account with display name `OpenCode Free`
- **AND** the account includes health status, base URL, model count, last checked time, and request usage derived from OpenCode Free sidecar request logs
- **AND** the account is present even when no API key is stored
