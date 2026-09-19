## ADDED Requirements

### Requirement: Route NVIDIA chat completions through the unified resolver

When NVIDIA is enabled, `POST /v1/chat/completions` whose effective model matches a NVIDIA full model or prefix MUST route to the configured NVIDIA API instead of Codex. Provider order MUST be `claude`, `openrouter`, `nvidia`, `orcarouter`, `omniroute`, `ollama`, `opencode_go`. Full-model exact match MUST beat prefixes.

API-key validation, reservations, and request logs MUST use the effective client model. The resolver wire model MUST be forwarded to NVIDIA.

The service MUST NOT dispatch NVIDIA models on `/v1/responses`.

Effort override MUST always force the operator value when set. DeepSeek V4 `reasoning_content` repair MUST run on the NVIDIA chat path.

#### Scenario: Pinned full model routes to NVIDIA

- **GIVEN** `nvidia_sidecar_enabled=true`
- **AND** full models include `z-ai/glm-5.3`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "z-ai/glm-5.3"`
- **THEN** the service forwards the request to `https://integrate.api.nvidia.com/v1/chat/completions`
- **AND** the forwarded payload includes `model: "z-ai/glm-5.3"`
- **AND** no Codex account is selected

#### Scenario: Strip prefix forwards the NVIDIA wire model

- **GIVEN** NVIDIA is enabled
- **AND** prefixes include `nvidia/` with strip true
- **WHEN** a client sends `model: "nvidia/z-ai/glm-5.3"`
- **THEN** the service routes to NVIDIA
- **AND** the forwarded payload includes `model: "z-ai/glm-5.3"`

#### Scenario: Full model beats OpenRouter prefixes

- **GIVEN** OpenRouter and NVIDIA are enabled
- **AND** OpenRouter prefixes include `z-ai/`
- **AND** NVIDIA full models include `z-ai/glm-5.3`
- **WHEN** a client sends `model: "z-ai/glm-5.3"`
- **THEN** the service routes to NVIDIA
- **AND** OpenRouter receives no request

#### Scenario: Disabled integration does not dispatch

- **GIVEN** `nvidia_sidecar_enabled=false`
- **WHEN** a client sends `model: "z-ai/glm-5.3"`
- **THEN** the service does not call NVIDIA

#### Scenario: Responses stay off NVIDIA

- **GIVEN** NVIDIA is enabled and owns `z-ai/glm-5.3`
- **WHEN** a client sends `POST /v1/responses` with that model
- **THEN** the service does not forward the request to NVIDIA
