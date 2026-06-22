## ADDED Requirements

### Requirement: Sidecar chat payloads apply a configured provider default reasoning effort

The service MUST inject the sidecar provider's configured default reasoning effort into the forwarded chat payload only when the incoming request has no explicit reasoning effort. Each sidecar provider (CLIProxyAPI/Claude, OpenRouter, OmniRoute, Ollama) has an independent, optional default effort stored in dashboard settings with allowed values `none`, `minimal`, `low`, `medium`, `high`, or `xhigh`; an unset (null) default MUST NOT change the payload. The injected default MUST NOT override an explicit client `reasoning_effort`, an explicit nested `reasoning.effort`, or (for Claude) a reasoning effort derived from the model-name suffix. For OpenRouter and OmniRoute the default fills the top-level `reasoning_effort`; for Ollama the default maps to the `think` field and MUST be applied only when the request would not otherwise enable thinking.

#### Scenario: Provider default fills missing effort

- **GIVEN** the OpenRouter sidecar default reasoning effort is configured as `high`
- **WHEN** a client calls `/v1/chat/completions` routed to OpenRouter without any `reasoning_effort` or `reasoning.effort`
- **THEN** the forwarded payload includes `reasoning_effort: "high"`

#### Scenario: Explicit client effort is preserved

- **GIVEN** the OmniRoute sidecar default reasoning effort is configured as `high`
- **WHEN** a client calls `/v1/chat/completions` routed to OmniRoute with `reasoning_effort: "low"`
- **THEN** the forwarded payload keeps `reasoning_effort: "low"` and the default is not applied

#### Scenario: Explicit nested reasoning effort is preserved

- **GIVEN** the OpenRouter sidecar default reasoning effort is configured as `high`
- **WHEN** a client calls `/v1/chat/completions` routed to OpenRouter with `reasoning: {"effort": "minimal"}`
- **THEN** the forwarded payload retains the nested `reasoning.effort: "minimal"` and the top-level default is not applied

#### Scenario: Claude model-name suffix beats the provider default

- **GIVEN** the CLIProxyAPI/Claude sidecar default reasoning effort is configured as `medium`
- **WHEN** a client calls `/v1/chat/completions` for a Claude model whose name suffix resolves to `high`
- **THEN** the forwarded payload uses the suffix effort `high` and the provider default is not applied

#### Scenario: Ollama default maps to the think field

- **GIVEN** the Ollama sidecar default reasoning effort is configured as `low`
- **WHEN** a client calls `/v1/chat/completions` routed to Ollama without enabling thinking
- **THEN** the forwarded payload sets the Ollama `think` field from the default and does not set a top-level `reasoning_effort`

#### Scenario: Unset default leaves the payload unchanged

- **GIVEN** a sidecar provider has no configured default reasoning effort (null)
- **WHEN** a client calls `/v1/chat/completions` routed to that provider without any reasoning effort
- **THEN** the forwarded payload contains no injected `reasoning_effort` and no injected thinking control
