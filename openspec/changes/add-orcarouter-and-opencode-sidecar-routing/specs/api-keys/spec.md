## ADDED Requirements

### Requirement: Use effective model for OrcaRouter API-key checks

API-key enforced model and allowed-model checks MUST use the effective client model for OrcaRouter sidecar requests. When OrcaRouter routing strips a prefix before forwarding to the upstream API, API-key validation, reservation accounting, and request logs MUST still use the original effective model requested by the client.

#### Scenario: Enforced model applies before OrcaRouter routing

- **GIVEN** an API key has enforced model `orcarouter/auto`
- **AND** OrcaRouter owns prefix `orcarouter/` with strip disabled
- **WHEN** the key sends `POST /v1/chat/completions` without an explicit model override
- **THEN** validation uses `orcarouter/auto`
- **AND** OrcaRouter receives wire model `orcarouter/auto`

#### Scenario: Allowed models use effective model

- **GIVEN** an API key allows only `orcarouter/auto`
- **AND** OrcaRouter owns prefix `orcarouter/` with strip disabled
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "orcarouter/auto"`
- **THEN** the request is allowed
- **AND** OrcaRouter receives wire model `orcarouter/auto`

### Requirement: Use effective model for OpenCode Zen API-key checks

API-key enforced model and allowed-model checks MUST use the effective client model for OpenCode Zen sidecar requests. When OpenCode Zen routing strips a prefix before forwarding to the upstream API, API-key validation, reservation accounting, and request logs MUST still use the original effective model requested by the client.

#### Scenario: Enforced model applies before OpenCode Zen strip

- **GIVEN** an API key has enforced model `opencode-zen/mimo-v2.5-free`
- **AND** OpenCode Zen owns prefix `opencode-zen/` with strip enabled
- **WHEN** the key sends `POST /v1/chat/completions` without an explicit model override
- **THEN** validation uses `opencode-zen/mimo-v2.5-free`
- **AND** OpenCode Zen receives wire model `mimo-v2.5-free`

#### Scenario: Allowed models use effective model

- **GIVEN** an API key allows only `opencode-zen/mimo-v2.5-free`
- **AND** OpenCode Zen owns prefix `opencode-zen/` with strip enabled
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "opencode-zen/mimo-v2.5-free"`
- **THEN** the request is allowed
- **AND** OpenCode Zen receives wire model `mimo-v2.5-free`

### Requirement: Use effective model for OpenCode Free API-key checks

API-key enforced model and allowed-model checks MUST use the effective client model for OpenCode Free sidecar requests. When OpenCode Free routing strips a prefix before forwarding to the upstream API, API-key validation, reservation accounting, and request logs MUST still use the original effective model requested by the client.

#### Scenario: Enforced model applies before OpenCode Free strip

- **GIVEN** an API key has enforced model `oc/big-pickle`
- **AND** OpenCode Free owns prefix `oc/` with strip enabled
- **WHEN** the key sends `POST /v1/chat/completions` without an explicit model override
- **THEN** validation uses `oc/big-pickle`
- **AND** OpenCode Free receives wire model `big-pickle`

#### Scenario: Allowed models use effective model

- **GIVEN** an API key allows only `oc/big-pickle`
- **AND** OpenCode Free owns prefix `oc/` with strip enabled
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "oc/big-pickle"`
- **THEN** the request is allowed
- **AND** OpenCode Free receives wire model `big-pickle`
