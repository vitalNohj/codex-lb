## MODIFIED Requirements

### Requirement: Participating integrations are a closed set

External model price resolution MUST apply to OpenRouter, OrcaRouter, CLIProxyAPI, NVIDIA, OpenCode Go, and configured OpenAI-compatible endpoints. Ollama and OmniRoute MUST NOT participate: their request-log cost stays `--` and their rows carry no price status.

#### Scenario: An excluded integration produces no pricing record

- **GIVEN** a request served by Ollama or OmniRoute
- **WHEN** the request log is written
- **THEN** no `external_model_prices` row is created
- **AND** the row's price status is NULL
- **AND** the request-log UI renders `--` with no unresolved marker

## ADDED Requirements

### Requirement: OpenAI-compatible serving catalogs read Unlid's published model rates

For an enabled OpenAI-compatible endpoint, the system MUST recognize the existing OpenRouter-style top-level `pricing.prompt` and `pricing.completion` USD-per-token rates, and Unlid's namespaced `unlid.pricing.input_usd_per_m` and `unlid.pricing.output_usd_per_m` USD-per-million-token rates. The serving catalog and runtime reference-price registry MUST agree on the selected format. The system MUST use nonnegative finite published rates including zero, MUST NOT guess the units of unrecognized fields, and MUST NOT treat an unreadable published rate or a nonempty Unlid pricing block with no recognized token-rate fields as a settled no-token-price answer. When both formats are present and non-null, the top-level format MUST take precedence. A null top-level block MUST NOT mask a valid Unlid block.

Catalog-calculated cost MUST retain its list-price provenance and MUST NOT be presented as Unlid's actual billed debit. The first request for a new model MUST remain cache-first and may have no cost while the price lookup completes.

#### Scenario: A Unlid listing supplies a calculated cost

- **GIVEN** an OpenAI-compatible serving catalog entry for `glm-5.3-flash-uncensored` with `unlid.pricing.input_usd_per_m = 0.42` and `unlid.pricing.output_usd_per_m = 1.68`
- **WHEN** a request after price resolution reports 13 input and 64 output tokens
- **THEN** the request-log cost is `13 * 0.42/1e6 + 64 * 1.68/1e6 = 0.00011298` USD
- **AND** its cost source is catalog-calculated, not upstream-billed

#### Scenario: A malformed Unlid rate does not settle without a price

- **GIVEN** a listed model with a nonnumeric or non-finite `unlid.pricing.input_usd_per_m` and a published output rate
- **WHEN** its serving catalog is consulted
- **THEN** the price is unparseable, not a settled no-token-rate answer
- **AND** maintenance preserves any previously stored valid rate

#### Scenario: A model without a published rate remains unpriced

- **GIVEN** a listed model without either recognized rate format
- **WHEN** its serving catalog is consulted
- **THEN** no rate is invented and it remains listed without a token price

#### Scenario: A previously settled Unlid model can be refreshed

- **GIVEN** an existing `not_token_priced` record for a Unlid model resolved before support for its format
- **WHEN** an operator runs `codex-lb model-prices refresh` with the endpoint enabled
- **THEN** a now-published valid rate resolves that record for future requests
- **AND** historical request-log rows are not retroactively rewritten
