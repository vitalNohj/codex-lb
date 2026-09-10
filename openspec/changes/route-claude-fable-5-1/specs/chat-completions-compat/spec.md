## ADDED Requirements

### Requirement: Claude Fable 5.1 sidecar requests keep the 5.1 wire model

The Claude sidecar chat-completions forward path MUST send Anthropic/CLIProxyAPI model id `claude-fable-5-1` when the client requested Fable 5.1, including dotted `5.1`, hyphen `5-1`, sidecar prefixes such as `cc/`, and reasoning-effort suffixes. It MUST NOT rewrite those ids to `claude-fable-5`. Unversioned Fable 5 ids MUST still forward as `claude-fable-5`. Canonical hyphenated ids with a trailing `-YYYYMMDD` release stamp MUST retain that stamp on the wire.

Fable 5.1 MUST use the same output bounds as Fable 5: a 32,768-token floor, a 128,000-token cap, and a 1,000,000-token context window. The estimated remaining context MUST constrain the output ceiling even when it falls below the floor.

#### Scenario: Hyphen 5.1 id is forwarded as claude-fable-5-1

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-fable-5-1`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5-1`

#### Scenario: Dotted 5.1 id is normalized to the Anthropic id

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-fable-5.1`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5-1`

#### Scenario: Thinking suffix on 5.1 does not collapse to Fable 5

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-fable-5-1-thinking-max`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5-1`
- **AND** the forwarded `reasoning_effort` is `max`

#### Scenario: Unversioned Fable 5 is unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-fable-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5`

#### Scenario: Fable 5.1 output is raised to the model floor

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-fable-5-1` and `max_tokens` 4096
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is `32768`
