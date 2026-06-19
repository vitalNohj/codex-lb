## ADDED Requirements

### Requirement: Record Ollama sidecar observability as normal HTTP traffic

Request logs MUST record Ollama sidecar rows with normal HTTP presentation and provider label `Ollama`. Ollama rows MUST use `source = "ollama_sidecar"`, MUST preserve the effective client model in log fields, MUST display transport as `HTTP`, and MUST NOT show a generic sidecar badge in the model column.

When Ollama responses provide token counts, request logs MUST record input tokens from `prompt_eval_count` and output tokens from `eval_count`. Request logs MUST keep `cost_usd` null unless existing pricing data supports a real cost calculation; missing Ollama pricing MUST NOT be converted to zero.

#### Scenario: Ollama request log row is understandable

- **GIVEN** an Ollama sidecar request succeeds
- **WHEN** an authenticated operator views Request Logs
- **THEN** the row shows transport `HTTP`
- **AND** the account/provider column shows `Ollama`
- **AND** the model column does not show a sidecar badge

#### Scenario: Ollama usage is recorded without invented cost

- **GIVEN** an Ollama response includes `prompt_eval_count: 10` and `eval_count: 20`
- **AND** no authoritative Ollama pricing entry exists
- **WHEN** the request log row is written
- **THEN** input tokens are recorded as `10`
- **AND** output tokens are recorded as `20`
- **AND** `cost_usd` is null

#### Scenario: Synthetic Ollama account appears

- **GIVEN** Ollama sidecar settings are configured or enabled
- **WHEN** an authenticated operator calls the Accounts API
- **THEN** the response includes a read-only synthetic account with display name `Ollama`
- **AND** the account includes health status, base URL, model count, last checked time, and request usage derived from Ollama sidecar request logs
