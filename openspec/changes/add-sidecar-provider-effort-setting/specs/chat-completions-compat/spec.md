## ADDED Requirements

### Requirement: Sidecar chat payloads apply a configured provider reasoning effort override

The service MUST force the sidecar provider's configured reasoning effort override onto the forwarded chat payload, overriding any client-supplied `reasoning_effort` or nested `reasoning.effort`. Each sidecar provider (CLIProxyAPI/Claude, OpenRouter, OmniRoute, Ollama) has an independent, optional override effort stored in dashboard settings with allowed values `none`, `minimal`, `low`, `medium`, `high`, or `xhigh`; an unset (null) override MUST NOT change the payload. When the override is applied it MUST write the configured value to the top-level `reasoning_effort` and remove any nested `reasoning.effort` so the forced value cannot be overridden downstream. A reasoning effort derived from a Claude model-name suffix (e.g. `-high`) is the highest precedence and MUST beat the override. For OpenRouter and OmniRoute the override fills the top-level `reasoning_effort`; for Ollama the override maps to the `think` field and MUST be applied even when the request already enabled thinking.

#### Scenario: Override fills missing effort

- **GIVEN** the OpenRouter sidecar reasoning effort override is configured as `high`
- **WHEN** a client calls `/v1/chat/completions` routed to OpenRouter without any `reasoning_effort` or `reasoning.effort`
- **THEN** the forwarded payload includes `reasoning_effort: "high"`

#### Scenario: Override replaces explicit client effort

- **GIVEN** the OmniRoute sidecar reasoning effort override is configured as `high`
- **WHEN** a client calls `/v1/chat/completions` routed to OmniRoute with `reasoning_effort: "low"`
- **THEN** the forwarded payload uses `reasoning_effort: "high"` and the client value is overridden

#### Scenario: Override replaces explicit nested reasoning effort

- **GIVEN** the OpenRouter sidecar reasoning effort override is configured as `high`
- **WHEN** a client calls `/v1/chat/completions` routed to OpenRouter with `reasoning: {"effort": "minimal"}`
- **THEN** the forwarded payload sets `reasoning_effort: "high"` and the nested `reasoning.effort` is removed

#### Scenario: Claude model-name suffix beats the override

- **GIVEN** the CLIProxyAPI/Claude sidecar reasoning effort override is configured as `medium`
- **WHEN** a client calls `/v1/chat/completions` for a Claude model whose name suffix resolves to `high`
- **THEN** the forwarded payload uses the suffix effort `high` and the override is not applied

#### Scenario: Ollama override maps to the think field

- **GIVEN** the Ollama sidecar reasoning effort override is configured as `low`
- **WHEN** a client calls `/v1/chat/completions` routed to Ollama
- **THEN** the forwarded payload sets the Ollama `think` field from the override and does not set a top-level `reasoning_effort`

#### Scenario: Unset override leaves the payload unchanged

- **GIVEN** a sidecar provider has no configured reasoning effort override (null)
- **WHEN** a client calls `/v1/chat/completions` routed to that provider without any reasoning effort
- **THEN** the forwarded payload contains no injected `reasoning_effort` and no injected thinking control
