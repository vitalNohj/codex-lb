## ADDED Requirements

### Requirement: Sidecar request logs persist the client-requested reasoning effort separately from the effective effort

The system MUST persist the client-requested reasoning effort and the effective (forwarded) reasoning effort as separate request-log fields for sidecar chat-completions traffic (CLIProxyAPI/Claude, OpenRouter, OmniRoute, Ollama). The requested value MUST be the reasoning effort present on the incoming request (top-level `reasoning_effort` or nested `reasoning.effort`) before any per-provider override, Claude model-name-suffix effort, or Ollama `think` mapping is applied, and MUST be `null` when the incoming request carried no reasoning effort. The effective `reasoning_effort` MUST record the effort actually forwarded to the provider. Historical sidecar rows recorded before this field existed MUST remain valid with a `null` requested effort.

#### Scenario: Provider override changes the effort

- **WHEN** a client sends a sidecar chat-completions request with `reasoning_effort: "medium"`
- **AND** the provider has a default reasoning effort override of `high`
- **THEN** the persisted request log entry records `requested_reasoning_effort = "medium"`
- **AND** the persisted request log entry records effective `reasoning_effort = "high"`

#### Scenario: No override leaves requested and effective equal

- **WHEN** a client sends a sidecar chat-completions request with `reasoning_effort: "high"`
- **AND** the provider has no default reasoning effort override
- **THEN** the persisted request log entry records `requested_reasoning_effort = "high"`
- **AND** the persisted request log entry records effective `reasoning_effort = "high"`

#### Scenario: Request omits reasoning effort

- **WHEN** a client sends a sidecar chat-completions request with no `reasoning_effort` and no nested `reasoning.effort`
- **AND** the provider has no default reasoning effort override
- **THEN** the persisted request log entry records `requested_reasoning_effort = null`
- **AND** the persisted request log entry records effective `reasoning_effort = null`

#### Scenario: Override injects an effort where the client sent none

- **WHEN** a client sends a sidecar chat-completions request with no reasoning effort
- **AND** the provider has a default reasoning effort override of `low`
- **THEN** the persisted request log entry records `requested_reasoning_effort = null`
- **AND** the persisted request log entry records effective `reasoning_effort = "low"`
