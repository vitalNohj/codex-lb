# external-model-pricing (delta)

## ADDED Requirements

### Requirement: Prompt-cache writes are recorded separately

The Claude CLIProxyAPI chat path MUST read cache-creation tokens from the sidecar usage, both from the non-streamed response body and from streamed usage chunks, in `prompt_tokens_details.cache_write_tokens` or `prompt_tokens_details.cached_creation_tokens`. The request log MUST persist them as `cache_write_input_tokens`, a part of `input_tokens` distinct from cached (read) input.

#### Scenario: A non-streamed Claude response with a cache write

- **GIVEN** a CLIProxyAPI chat response reporting `prompt_tokens` 30,000, `cached_tokens` 0 and `cache_write_tokens` 29,990
- **WHEN** the request is logged
- **THEN** the request log records 30,000 input tokens, 0 cached input tokens and 29,990 cache-write input tokens

#### Scenario: A streamed Claude response with a cache read and no write

- **GIVEN** a streamed CLIProxyAPI chat response whose trailing usage chunk reports `cached_tokens` 29,990 and no cache write
- **WHEN** the request is logged
- **THEN** 29,990 cached input tokens and 0 cache-write input tokens are recorded

### Requirement: Prompt-cache writes are priced at the 1-hour write rate

The calculated cost MUST price written tokens at twice the input token rate, which is Anthropic's 1-hour cache-write price. It MUST price cached input at the cache-read rate, and only the input that is neither read nor written at the input rate. Written tokens MUST be clamped so that reads plus writes never exceed the prompt. A request with no writes MUST keep exactly the cost it had before writes were recorded.

#### Scenario: A cache write costs twice the input rate

- **GIVEN** a request recording 30,000 input tokens, of which 29,990 are cache writes and none are cache reads
- **WHEN** its cost is calculated
- **THEN** 29,990 tokens are charged at twice the input rate and 10 tokens at the input rate

#### Scenario: Request details show the cache-write part of a catalog-priced cost

- **GIVEN** a CLIProxyAPI Claude request priced from its resolved catalog rate, with cache writes
- **WHEN** it is logged and its details are listed
- **THEN** the request log stores the cache-write part of the cost as `cache_write_input_cost_usd`, at the rate that priced it
- **AND** the cost breakdown reports that part with the total, leaving the parts that were not stored unknown
- **AND** a billed cost reports no cache-write part

#### Scenario: Requests without writes keep their cost

- **GIVEN** a request whose usage reports no cache write
- **WHEN** its cost is calculated
- **THEN** the cost is bit-identical to the cost calculated from input, cached input and output alone
