## ADDED Requirements

### Requirement: Claude Haiku 5.5 sidecar requests keep the 5.5 wire model

The Claude sidecar chat-completions forward path MUST forward `claude-haiku-5-5` unchanged when routing produced that id. A different spelling, including dotted `claude-haiku-5.5`, a trailing `-YYYYMMDD` release stamp, and a trailing thinking or effort suffix, MUST be forwarded as that spelling after routing. The exact id `claude-haiku-5-5` MUST use a 32,768-token output floor, a 128,000-token output cap, and a 1,000,000-token context window. The estimated remaining context MUST constrain the output ceiling even when it falls below the floor.

#### Scenario: Hyphen 5.5 id is forwarded as claude-haiku-5-5

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-haiku-5-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-haiku-5-5`

#### Scenario: Dotted 5.5 id is forwarded as typed

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-haiku-5.5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-haiku-5.5`

#### Scenario: A thinking suffix stays on the forwarded id

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-haiku-5-5-thinking-max`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-haiku-5-5-thinking-max`
- **AND** the payload does not set `reasoning_effort` from that suffix

#### Scenario: Dated Haiku 5.5 keeps its release stamp

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `claude-haiku-5-5-20261007`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-haiku-5-5-20261007`

#### Scenario: Unversioned Haiku 4.5 is unchanged

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-haiku-4-5`
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `model` is `claude-haiku-4-5`

#### Scenario: Haiku 5.5 output is raised to the model floor

- **GIVEN** a client calls `/v1/chat/completions` routed to the Claude sidecar with model `cc/claude-haiku-5-5` and `max_tokens` 4096
- **WHEN** the forwarded payload is built
- **THEN** the forwarded `max_tokens` is `32768`

### Requirement: Stored CLIProxyAPI full models include Claude Haiku 5.5

Upgrading dashboard settings MUST append `claude-haiku-5-5` to the CLIProxyAPI full-model list when that id is absent. Existing entries and their order MUST be preserved. A list that already contains the id, including a different letter case, MUST be left unchanged. Invalid JSON MUST be left unchanged. Downgrade MUST remove `claude-haiku-5-5` only from rows this upgrade appended. A pin that was already stored MUST stay. A settings save that removes `claude-haiku-5-5` from the CLIProxyAPI full-model list MUST keep that row marked as processed, so a replayed upgrade does not add it again. A settings save that adds `claude-haiku-5-5` back MUST end the upgrade's ownership of that row, so downgrade leaves the operator's pin.

#### Scenario: Upgrade appends Haiku 5.5 without reordering

- **GIVEN** stored CLIProxyAPI full models are `claude-opus-5` then `claude-haiku-4-5`
- **WHEN** the upgrade runs
- **THEN** the full-model list is `claude-opus-5`, `claude-haiku-4-5`, `claude-haiku-5-5` in that order

#### Scenario: Upgrade leaves an existing Haiku 5.5 entry in place

- **GIVEN** stored CLIProxyAPI full models already contain `claude-haiku-5-5`
- **WHEN** the upgrade runs
- **THEN** the stored JSON is unchanged

#### Scenario: Downgrade removes only Haiku 5.5 this upgrade appended

- **GIVEN** stored CLIProxyAPI full models were `claude-opus-5` then `claude-haiku-4-5` before this upgrade appended `claude-haiku-5-5`
- **WHEN** the downgrade runs
- **THEN** the full-model list is `claude-opus-5` then `claude-haiku-4-5`

#### Scenario: Downgrade leaves a pin that predated the upgrade

- **GIVEN** stored CLIProxyAPI full models already contained `claude-haiku-5-5` before the upgrade
- **WHEN** the downgrade runs
- **THEN** that `claude-haiku-5-5` entry is still present

#### Scenario: A replayed upgrade does not restore a pin the operator removed

- **GIVEN** this upgrade appended `claude-haiku-5-5` to the stored CLIProxyAPI full models
- **AND** the operator then saved settings without `claude-haiku-5-5`
- **WHEN** the upgrade is replayed after a legacy-revision remap
- **THEN** the full-model list still does not contain `claude-haiku-5-5`

#### Scenario: Downgrade leaves a pin the operator removed and added back

- **GIVEN** this upgrade appended `claude-haiku-5-5` to the stored CLIProxyAPI full models
- **AND** the operator then saved settings without `claude-haiku-5-5`, and later saved them with it again
- **WHEN** the downgrade runs
- **THEN** that `claude-haiku-5-5` entry is still present
