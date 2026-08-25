## ADDED Requirements

### Requirement: Advertise configured OrcaRouter full models only

`/v1/models` MUST advertise configured OrcaRouter full models only when the OrcaRouter integration is enabled. Discovered OrcaRouter models MUST NOT appear in `/v1/models` unless the operator has also configured the model as an OrcaRouter full model.

OrcaRouter model entries MUST use the configured full model ID unchanged, MUST be marked as owned by `orcarouter` unless discovery provides a more specific owner, and MUST advertise chat-completions support through the same sidecar metadata shape used by existing sidecar models. The service MUST apply API-key enforced-model and allowed-model filtering to OrcaRouter entries using the effective configured model ID.

#### Scenario: Configured OrcaRouter model appears

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter full models include `orcarouter/auto`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes a model entry with `id: "orcarouter/auto"`
- **AND** the entry has `owned_by: "orcarouter"`

#### Scenario: Discovered-only OrcaRouter model does not appear

- **GIVEN** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter model discovery returns `openai/gpt-5.5`
- **AND** OrcaRouter full models do not include `openai/gpt-5.5`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include `openai/gpt-5.5` as an OrcaRouter-owned entry

#### Scenario: Disabled OrcaRouter contributes no entries

- **GIVEN** the OrcaRouter sidecar is disabled
- **AND** OrcaRouter full models include `orcarouter/auto`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include an OrcaRouter-owned `orcarouter/auto` entry

#### Scenario: OrcaRouter models respect API-key allowlist

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** the OrcaRouter sidecar is enabled
- **AND** OrcaRouter full models include `orcarouter/auto`
- **WHEN** the API key calls `GET /v1/models`
- **THEN** the response does not include `orcarouter/auto`

### Requirement: Advertise configured OpenCode Zen full models only

`/v1/models` MUST advertise configured OpenCode Zen full models only when the OpenCode Zen integration is enabled. Discovered OpenCode Zen models MUST NOT appear in `/v1/models` unless the operator has also configured the model as an OpenCode Zen full model.

OpenCode Zen model entries MUST use the configured full model ID unchanged, MUST be marked as owned by `opencode-zen` unless discovery provides a more specific owner, and MUST advertise chat-completions support through the same sidecar metadata shape used by existing sidecar models. The service MUST apply API-key enforced-model and allowed-model filtering to OpenCode Zen entries using the effective configured model ID.

#### Scenario: Configured OpenCode Zen model appears

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** OpenCode Zen full models include `opencode-zen/mimo-v2.5-free`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes a model entry with `id: "opencode-zen/mimo-v2.5-free"`
- **AND** the entry has `owned_by: "opencode-zen"`

#### Scenario: Discovered-only OpenCode Zen model does not appear

- **GIVEN** the OpenCode Zen sidecar is enabled
- **AND** OpenCode Zen model discovery returns `mimo-v2.5-free`
- **AND** OpenCode Zen full models do not include `opencode-zen/mimo-v2.5-free` or `mimo-v2.5-free`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include `mimo-v2.5-free`

#### Scenario: Disabled OpenCode Zen contributes no entries

- **GIVEN** the OpenCode Zen sidecar is disabled
- **AND** OpenCode Zen full models include `opencode-zen/mimo-v2.5-free`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include an OpenCode-Zen-owned `opencode-zen/mimo-v2.5-free` entry

#### Scenario: OpenCode Zen models respect API-key allowlist

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** the OpenCode Zen sidecar is enabled
- **AND** OpenCode Zen full models include `opencode-zen/mimo-v2.5-free`
- **WHEN** the API key calls `GET /v1/models`
- **THEN** the response does not include `opencode-zen/mimo-v2.5-free`

### Requirement: Advertise configured OpenCode Free full models only

`/v1/models` MUST advertise configured OpenCode Free full models only when the OpenCode Free integration is enabled. Discovered OpenCode Free models MUST NOT appear in `/v1/models` unless the operator has also configured the model as an OpenCode Free full model.

OpenCode Free model entries MUST use the configured full model ID unchanged, MUST be marked as owned by `opencode` unless discovery provides a more specific owner, and MUST advertise chat-completions support through the same sidecar metadata shape used by existing sidecar models. The service MUST apply API-key enforced-model and allowed-model filtering to OpenCode Free entries using the effective configured model ID.

#### Scenario: Configured OpenCode Free model appears

- **GIVEN** the OpenCode Free sidecar is enabled
- **AND** OpenCode Free full models include `oc/big-pickle`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes a model entry with `id: "oc/big-pickle"`
- **AND** the entry has `owned_by: "opencode"`

#### Scenario: Discovered-only OpenCode Free model does not appear

- **GIVEN** the OpenCode Free sidecar is enabled
- **AND** OpenCode Free model discovery returns `big-pickle`
- **AND** OpenCode Free full models do not include `oc/big-pickle` or `big-pickle`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include `big-pickle`

#### Scenario: Disabled OpenCode Free contributes no entries

- **GIVEN** the OpenCode Free sidecar is disabled
- **AND** OpenCode Free full models include `oc/big-pickle`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include an OpenCode-owned `oc/big-pickle` entry

#### Scenario: OpenCode Free models respect API-key allowlist

- **GIVEN** an API key has `allowed_models: ["gpt-5.4"]`
- **AND** the OpenCode Free sidecar is enabled
- **AND** OpenCode Free full models include `oc/big-pickle`
- **WHEN** the API key calls `GET /v1/models`
- **THEN** the response does not include `oc/big-pickle`
