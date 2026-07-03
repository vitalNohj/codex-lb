## ADDED Requirements

### Requirement: Claude sidecar chat payloads raise client max_tokens to a per-model output floor

The service MUST raise a client-supplied `max_tokens` on Claude sidecar chat-completions payloads to a per-model output-token floor and MUST clamp the result to the model's published maximum output tokens, applied on every forwarded request. The floor/cap lookup keys on the canonical Claude model resolved from the wire model. A request without a client-supplied `max_tokens` MUST be forwarded without an injected value, and a model with no configured cap MUST be forwarded unchanged. When present, `max_completion_tokens` MUST receive the same floor/cap treatment. The native Codex Responses path and other sidecar providers are unaffected.

#### Scenario: Cursor default 4096 is raised to the model floor

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-fable-5` and `max_tokens: 4096`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` equals the configured floor for `claude-fable-5` (32768)

#### Scenario: Client value above the floor is preserved

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-fable-5` and `max_tokens: 64000`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` remains 64000

#### Scenario: Client value above the model cap is clamped

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-fable-5` and `max_tokens: 200000`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is clamped to the model maximum (128000)

#### Scenario: Absent max_tokens stays absent

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar without `max_tokens`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded payload contains no `max_tokens`

#### Scenario: Unknown Claude model is forwarded unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with a model that has no configured output cap and `max_tokens: 4096`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` remains 4096
