## ADDED Requirements

### Requirement: Claude Opus 5.5 sidecar requests keep the 5.5 wire model

The Claude sidecar chat-completions forward path MUST send Anthropic/CLIProxyAPI model id `claude-opus-5-5` when the client requested Opus 5.5, including dotted `5.5`, hyphen `5-5`, sidecar prefixes such as `cc/`, and reasoning-effort suffixes. It MUST NOT rewrite those ids to `claude-opus-5`. Unversioned Opus 5 ids MUST still forward as `claude-opus-5`. Canonical hyphenated ids with a trailing `-YYYYMMDD` release stamp MUST retain that stamp on the wire.

Opus 5.5 MUST use a 32,768-token output floor, a 128,000-token output cap, and a 1,000,000-token context window. The estimated remaining context MUST constrain the output ceiling even when it falls below the floor.

#### Scenario: Hyphen 5.5 id is forwarded as claude-opus-5-5

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-opus-5-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5-5`

#### Scenario: Dotted 5.5 id is normalized to the Anthropic id

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-opus-5.5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5-5`

#### Scenario: Thinking suffix on 5.5 does not collapse to Opus 5

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-opus-5-5-thinking-max`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-opus-5-5`
- **AND** the forwarded `reasoning_effort` is `max`

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

### Requirement: Stored CLIProxyAPI full models include Claude Opus 5.5

Upgrading dashboard settings MUST append `claude-opus-5-5` to the CLIProxyAPI full-model list when that id is absent. Existing entries and their order MUST be preserved. A list that already contains the id, including a different letter case, MUST be left unchanged. Invalid JSON MUST be left unchanged. Downgrade MUST remove `claude-opus-5-5` only from rows this upgrade appended. A pin that was already stored MUST stay.

#### Scenario: Upgrade appends Opus 5.5 without reordering

- **GIVEN** stored CLIProxyAPI full models are `claude-opus-5` then `claude-fable-5-1`
- **WHEN** the upgrade runs
- **THEN** the full-model list is `claude-opus-5`, `claude-fable-5-1`, `claude-opus-5-5` in that order

#### Scenario: Upgrade leaves an existing Opus 5.5 entry in place

- **GIVEN** stored CLIProxyAPI full models already contain `claude-opus-5-5`
- **WHEN** the upgrade runs
- **THEN** the stored JSON is unchanged

#### Scenario: Downgrade removes only Opus 5.5 this upgrade appended

- **GIVEN** stored CLIProxyAPI full models were `claude-opus-5` then `claude-fable-5-1` before this upgrade appended `claude-opus-5-5`
- **WHEN** the downgrade runs
- **THEN** the full-model list is `claude-opus-5` then `claude-fable-5-1`

#### Scenario: Downgrade leaves a pin that predated the upgrade

- **GIVEN** stored CLIProxyAPI full models already contained `claude-opus-5-5` before the upgrade
- **WHEN** the downgrade runs
- **THEN** that `claude-opus-5-5` entry is still present
