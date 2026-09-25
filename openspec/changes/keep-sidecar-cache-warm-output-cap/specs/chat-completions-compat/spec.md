## ADDED Requirements

### Requirement: Claude sidecar chat payloads forward a minimal output cap unchanged

The Claude sidecar chat-completions forward path MUST forward a client-supplied `max_tokens` or `max_completion_tokens` of 16 or less unchanged. It MUST NOT raise such a value to the model output floor. This keeps prompt-cache keep-warm replays, which ask for a 1-token answer, a cache read instead of a full response. A value above 16 MUST keep the existing per-model floor, cap, and context-window guard.

#### Scenario: A 1-token keep-warm cap is forwarded unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5-5` and `max_tokens: 1`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is 1

#### Scenario: The 16-token minimum is forwarded unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5-5` and `max_completion_tokens: 16`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_completion_tokens` is 16

#### Scenario: A cap just above the minimum still gets the floor

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5-5` and `max_tokens: 17`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is 32768
