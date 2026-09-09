## ADDED Requirements

### Requirement: CLIProxyAPI discovered models are advertised when routable

When CLIProxyAPI routing is enabled, `GET /v1/models` MUST include models returned by the CLIProxyAPI `/v1/models` endpoint that the unified sidecar resolver would route to CLIProxyAPI, in addition to configured CLIProxyAPI full-model IDs. Discovered IDs that would not resolve to CLIProxyAPI MUST NOT be advertised unless they are also configured as CLIProxyAPI full models.

An advertised ID MUST reach the model it names: a discovered ID MUST NOT be advertised when the resolver would forward a wire model different from the advertised ID. This excludes a discovered ID that itself begins with a configured `strip` prefix, because dispatch removes that prefix and the client would reach a different model than the catalog listed. Configured full-model IDs are unaffected, since the resolver's full-model pass forwards them unchanged.

Configured full-model IDs MUST still be advertised even when they are absent from the discovered list. Other sidecar integrations keep their existing advertising rules.

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

#### Scenario: A discovered id that dispatch would rewrite is omitted

- **GIVEN** CLIProxyAPI is enabled
- **AND** CLIProxyAPI prefixes include `claude` with strip disabled and `cp-` with strip enabled
- **AND** the CLIProxyAPI full-model list is empty
- **AND** CLIProxyAPI `/v1/models` includes `cp-claude-sonnet`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response does not include `cp-claude-sonnet`
- **AND** every advertised CLIProxyAPI id dispatches to a wire model equal to that id

#### Scenario: A pinned full model under a strip prefix stays advertised

- **GIVEN** CLIProxyAPI is enabled
- **AND** CLIProxyAPI prefixes include `cp-` with strip enabled
- **AND** CLIProxyAPI full models include `cp-claude-sonnet`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `id: "cp-claude-sonnet"`
- **AND** a request for `cp-claude-sonnet` forwards `cp-claude-sonnet` to CLIProxyAPI

#### Scenario: Pinned full models still appear when discovery omits them

- **GIVEN** CLIProxyAPI is enabled
- **AND** CLIProxyAPI full models include `claude-sonnet-4-5-20250929`
- **AND** CLIProxyAPI `/v1/models` does not include that id
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `id: "claude-sonnet-4-5-20250929"`
