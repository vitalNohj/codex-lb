## MODIFIED Requirements

### Requirement: Claude Fable 5.1 sidecar requests keep the 5.1 wire model

The Claude sidecar chat-completions forward path MUST send `claude-fable-5-1` when routing produced that id, and MUST NOT rewrite it to `claude-fable-5`. A different spelling, including dotted `claude-fable-5.1` and a trailing thinking or effort suffix, MUST be forwarded as that spelling after routing. The exact id `claude-fable-5-1` MUST use a 32,768-token output floor, a 128,000-token output cap, and a 1,000,000-token context window. The estimated remaining context MUST constrain the output ceiling even when it falls below the floor.

#### Scenario: Hyphen 5.1 id is forwarded as claude-fable-5-1

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-fable-5-1`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5-1`

#### Scenario: Dotted 5.1 id is forwarded as typed

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-fable-5.1`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5.1`

#### Scenario: A thinking suffix stays on the forwarded id

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-fable-5-1-thinking-max`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5-1-thinking-max`
- **AND** the payload does not set `reasoning_effort` from that suffix

#### Scenario: Unversioned Fable 5 is unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-fable-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-fable-5`

#### Scenario: The exact Fable 5.1 id raises output to the model floor

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-fable-5-1` and `max_tokens` 4096
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is `32768`

### Requirement: Claude Opus 5.5 sidecar requests keep the 5.5 wire model

The Claude sidecar chat-completions forward path MUST send `claude-opus-5-5` when routing produced that id, and MUST NOT rewrite it to `claude-opus-5`. A different spelling, including dotted `claude-opus-5.5`, a trailing `-YYYYMMDD` release stamp, and a trailing thinking or effort suffix, MUST be forwarded as that spelling after routing. The exact id `claude-opus-5-5` MUST use a 32,768-token output floor, a 128,000-token output cap, and a 1,000,000-token context window. The estimated remaining context MUST constrain the output ceiling even when it falls below the floor.

#### Scenario: Hyphen 5.5 id is forwarded as claude-opus-5-5

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5-5`

#### Scenario: Dotted 5.5 id is forwarded as typed

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5.5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5.5`

#### Scenario: A thinking suffix stays on the forwarded id

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5-5-thinking-max`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5-5-thinking-max`
- **AND** the payload does not set `reasoning_effort` from that suffix

#### Scenario: Dated Opus 5.5 keeps its release stamp

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-opus-5-5-20260922`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5-5-20260922`

#### Scenario: Unversioned Opus 5 is unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5`

#### Scenario: Opus 5.5 output is raised to the model floor

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5-5` and `max_tokens` 4096
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is `32768`

### Requirement: Claude Sonnet 5.5 sidecar requests keep the 5.5 wire model

The Claude sidecar chat-completions forward path MUST send `claude-sonnet-5-5` when routing produced that id, and MUST NOT rewrite it to `claude-sonnet-5`. A different spelling, including dotted `claude-sonnet-5.5`, a trailing `-YYYYMMDD` release stamp, and a trailing thinking or effort suffix, MUST be forwarded as that spelling after routing. The exact id `claude-sonnet-5-5` MUST use a 32,768-token output floor, a 128,000-token output cap, and a 1,000,000-token context window. The estimated remaining context MUST constrain the output ceiling even when it falls below the floor.

#### Scenario: Hyphen 5.5 id is forwarded as claude-sonnet-5-5

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-sonnet-5-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-5-5`

#### Scenario: Dotted 5.5 id is forwarded as typed

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-sonnet-5.5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-5.5`

#### Scenario: A thinking suffix stays on the forwarded id

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-sonnet-5-5-thinking-max`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-5-5-thinking-max`
- **AND** the payload does not set `reasoning_effort` from that suffix

#### Scenario: Dated Sonnet 5.5 keeps its release stamp

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-sonnet-5-5-20260928`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-5-5-20260928`

#### Scenario: Unversioned Sonnet 5 is unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-sonnet-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-5`

#### Scenario: Sonnet 5.5 output is raised to the model floor

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-sonnet-5-5` and `max_tokens` 4096
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is `32768`

### Requirement: Claude catalog ids are not folded into a shorter family

The Claude sidecar chat-completions forward path MUST forward the model id produced by sidecar routing. Routing MUST remove a prefix only when that prefix is configured to strip, and MUST otherwise leave the requested id unchanged. The forward path MUST NOT rename that id, MUST NOT remove a release date, MUST NOT remove a reasoning-effort or thinking suffix, and MUST NOT map a dotted version onto a hyphenated id. A longer id MUST NOT be rewritten to a shorter family id. A discovered upstream id MUST be advertised on `GET /v1/models` when dispatch forwards that same id. A discovered id whose strip prefix would send a different id MUST stay out of that catalog. A full model pinned on the integration MUST stay advertised.

#### Scenario: A future catalog id is forwarded as itself

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-haiku-5-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-haiku-5-5`

#### Scenario: A thinking suffix is forwarded as typed

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-opus-4-7-thinking-high`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-4-7-thinking-high`
- **AND** the payload does not set `reasoning_effort` from that suffix

#### Scenario: A dated release stamp stays on the wire

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-sonnet-4-5-20250929`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-4-5-20250929`

#### Scenario: A longer id is not rewritten to a shorter family

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-sonnet-5-50`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-sonnet-5-50`

#### Scenario: A discovered suffixed id is advertised and dispatched as itself

- **GIVEN** CLIProxyAPI model discovery returns `claude-opus-4-7-high`
- **WHEN** a client lists models and then calls `/v1/chat/completions` with that id
- **THEN** `GET /v1/models` includes `claude-opus-4-7-high`
- **AND** the forwarded `model` is `claude-opus-4-7-high`

#### Scenario: A strip-prefix discovered id stays out of the catalog

- **GIVEN** the Claude routing prefix `cp-` strips and CLIProxyAPI model discovery returns `cp-claude-sonnet`
- **WHEN** a client lists models
- **THEN** `GET /v1/models` does not include `cp-claude-sonnet`
