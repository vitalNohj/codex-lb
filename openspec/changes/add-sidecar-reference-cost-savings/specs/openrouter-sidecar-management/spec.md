## ADDED Requirements

### Requirement: OpenRouter model pricing is parsed at runtime

The system MUST parse the per-model `pricing` object returned by the OpenRouter sidecar `/models` response into model pricing usable for cost calculations. OpenRouter reports `pricing.prompt`, `pricing.completion`, and (when present) `pricing.input_cache_read` as USD-per-token decimal strings; the system MUST convert these to per-1M-token rates (`input_per_1m`, `output_per_1m`, `cached_input_per_1m`). Entries with absent, non-numeric, or unparseable pricing MUST be treated as having no runtime pricing rather than raising an error or recording zero rates.

#### Scenario: Paid model pricing is parsed into per-1M rates
- **WHEN** the OpenRouter `/models` response includes a model whose `pricing.prompt` is `"0.0000008"` and `pricing.completion` is `"0.000004"`
- **THEN** the system records that model's runtime pricing as `input_per_1m = 0.8` and `output_per_1m = 4.0`

#### Scenario: Missing or unparseable pricing yields no runtime price
- **WHEN** an OpenRouter `/models` entry omits `pricing` or contains a non-numeric pricing value
- **THEN** the system records no runtime pricing for that model
- **AND** the models fetch still succeeds for the remaining entries

### Requirement: Runtime pricing overlays the static pricing table for reference cost

The system MUST provide a reference-cost pricing lookup that consults runtime OpenRouter pricing first and falls back to the static built-in pricing table when no runtime price is available. This reference lookup MUST NOT change how actual request `cost_usd` is computed.

#### Scenario: Runtime price is preferred for a model absent from the static table
- **WHEN** a model has runtime OpenRouter pricing but no entry in the static pricing table
- **AND** a reference-cost lookup is performed for that model
- **THEN** the system returns the runtime pricing

#### Scenario: Static table is used when runtime price is unavailable
- **WHEN** a model has no runtime OpenRouter pricing but has an entry in the static pricing table
- **AND** a reference-cost lookup is performed for that model
- **THEN** the system returns the static pricing

### Requirement: Free models resolve to their paid-equivalent reference price

When resolving the reference price for a model whose name marks it as free (for example a `:free`, `-free`, or `_free` suffix or segment), the system MUST attempt to resolve the paid-equivalent model by removing the free marker and looking up that model's reference price. When no paid equivalent can be resolved, the reference price MUST be treated as unavailable.

#### Scenario: Free variant uses paid variant pricing
- **WHEN** a request used model `vendor/model-x:free`
- **AND** runtime pricing exists for `vendor/model-x`
- **THEN** the reference price for the free request is the pricing of `vendor/model-x`

#### Scenario: No paid equivalent yields no reference price
- **WHEN** a request used a free model with no resolvable paid equivalent in runtime or static pricing
- **THEN** the reference price is unavailable
- **AND** the request's reference cost is not recorded
