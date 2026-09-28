## ADDED Requirements

### Requirement: Claude catalog ids are not folded into a shorter family

The Claude sidecar chat-completions forward path MUST send the requested model id after only these normalizations: removal of one leading `cc/`, `cp-`, or `cp_` routing prefix; removal of a trailing reasoning-effort suffix, including an adjacent `thinking` or `reasoning` marker, into `reasoning_effort`; and dotted-version normalization already performed by `resolve_versioned_model_id`. It MUST NOT rewrite that id to a shorter family id through `DEFAULT_MODEL_ALIASES`. A trailing `-YYYYMMDD` release stamp MUST stay on the forwarded model. A model id outside those normalizations, including a longer sibling or a future catalog id, MUST be forwarded unchanged.

#### Scenario: A future catalog id is forwarded as itself

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-haiku-5-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-haiku-5-5`

#### Scenario: A thinking suffix peels effort without shortening the model version

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-opus-4-7-thinking-high`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-4-7`
- **AND** the forwarded `reasoning_effort` is `high`

#### Scenario: A dated release stamp stays on the wire

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-sonnet-4-5-20250929`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-4-5-20250929`

#### Scenario: A longer id is not rewritten to a shorter family

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-sonnet-5-50`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-5-50`
