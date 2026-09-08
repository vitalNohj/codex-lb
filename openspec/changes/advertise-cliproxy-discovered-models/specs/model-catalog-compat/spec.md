## ADDED Requirements

### Requirement: CLIProxyAPI discovered models are advertised when routable

When CLIProxyAPI routing is enabled, `GET /v1/models` MUST include models returned by the CLIProxyAPI `/v1/models` endpoint that the unified sidecar resolver would route to CLIProxyAPI, in addition to configured CLIProxyAPI full-model IDs. Discovered IDs that would not resolve to CLIProxyAPI MUST NOT be advertised unless they are also configured as CLIProxyAPI full models. Configured full-model IDs MUST still be advertised even when they are absent from the discovered list. Other sidecar integrations keep their existing advertising rules.

#### Scenario: Discovered Claude models appear without a full-model pin

- **GIVEN** CLIProxyAPI is enabled
- **AND** CLIProxyAPI prefixes include `claude`
- **AND** the CLIProxyAPI full-model list is empty
- **AND** CLIProxyAPI `/v1/models` includes `claude-sonnet-4-5-20250929`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `id: "claude-sonnet-4-5-20250929"`
- **AND** that entry has `owned_by: "anthropic"` unless CLIProxyAPI returned a different owner for that id

#### Scenario: Discovered models that would not route to CLIProxyAPI are omitted

- **GIVEN** CLIProxyAPI is enabled
- **AND** CLIProxyAPI prefixes include `claude` and `cc/`
- **AND** the CLIProxyAPI full-model list is empty
- **AND** CLIProxyAPI `/v1/models` includes `gemini-2.5-pro`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include `gemini-2.5-pro`

#### Scenario: Pinned full models still appear when discovery omits them

- **GIVEN** CLIProxyAPI is enabled
- **AND** CLIProxyAPI full models include `claude-sonnet-4-5-20250929`
- **AND** CLIProxyAPI `/v1/models` does not include that id
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `id: "claude-sonnet-4-5-20250929"`
