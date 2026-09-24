## ADDED Requirements

### Requirement: Sidecar models advertise their real context window on /v1/models

When serving `GET /v1/models`, the system SHALL advertise, for each external-integration (sidecar) model entry, a single context window resolved in this order:

1. the operator's `model_context_window_overrides` entry for the advertised model id;
2. for a Claude sidecar model, the published context window of its canonical model, the same value the sidecar dispatch path uses to bound output tokens;
3. the window reported by the provider's own model catalog entry (`context_length`, `context_window`, or `top_provider.context_length`, positive integers only);
4. 200000.

`context_length`, `contextLength` and `capabilities.context_length` MUST carry the same resolved value. A strip-prefix alias MUST advertise the window of the upstream model it names.

#### Scenario: Claude 1M model advertises 1M under its bare and prefixed ids

- **GIVEN** the Claude sidecar lists `claude-opus-5-5` with strip prefix `cc/`
- **WHEN** a client calls `GET /v1/models`
- **THEN** `claude-opus-5-5` and `cc/claude-opus-5-5` both report `context_length=1000000`, `contextLength=1000000` and `capabilities.context_length=1000000`

#### Scenario: Claude model with a 200k window keeps it

- **WHEN** the Claude sidecar lists `claude-sonnet-4-5-20250929`
- **THEN** its entry reports `context_length=200000`

#### Scenario: Catalog-reported window is advertised

- **GIVEN** OpenRouter's catalog entry for `deepseek/deepseek-chat` has `context_length=163840`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the entry reports `context_length=163840`

#### Scenario: Operator override wins

- **GIVEN** `model_context_window_overrides` maps `deepseek/deepseek-pin` to `96000` and its catalog entry reports `64000`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the entry reports `context_length=96000`

#### Scenario: Unknown window keeps the default

- **WHEN** a sidecar model has no override, no published Claude window and no usable catalog window
- **THEN** its entry reports `context_length=200000`
