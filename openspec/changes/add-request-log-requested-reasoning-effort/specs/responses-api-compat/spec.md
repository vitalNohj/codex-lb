## ADDED Requirements

### Requirement: Request logs persist the client-requested reasoning effort separately from the effective effort

The system MUST persist the client-requested reasoning effort and the effective (forwarded) reasoning effort as separate request-log fields, capturing the requested value before API-key enforcement or model-alias normalization mutates it. The requested value MUST be the reasoning effort present on the incoming request (top-level `reasoning_effort` or nested `reasoning.effort`), and MUST be `null` when the incoming request carried no reasoning effort. The existing `reasoning_effort` field continues to record the effective effort that was forwarded upstream. Historical rows recorded before this field existed MUST remain valid with a `null` requested effort.

#### Scenario: API key enforcement raises the effort

- **WHEN** a client sends a Responses request with `reasoning.effort: "medium"`
- **AND** the API key enforces reasoning effort `xhigh`
- **THEN** the persisted request log entry records `requested_reasoning_effort = "medium"`
- **AND** the persisted request log entry records effective `reasoning_effort = "xhigh"`

#### Scenario: No enforcement leaves requested and effective equal

- **WHEN** a client sends a Responses request with `reasoning.effort: "high"`
- **AND** no API-key reasoning-effort enforcement applies
- **THEN** the persisted request log entry records `requested_reasoning_effort = "high"`
- **AND** the persisted request log entry records effective `reasoning_effort = "high"`

#### Scenario: Request omits reasoning effort

- **WHEN** a client sends a Responses request with no `reasoning_effort` and no nested `reasoning.effort`
- **AND** no API-key reasoning-effort enforcement applies
- **THEN** the persisted request log entry records `requested_reasoning_effort = null`
- **AND** the persisted request log entry records effective `reasoning_effort = null`

#### Scenario: Enforcement injects an effort where the client sent none

- **WHEN** a client sends a Responses request with no reasoning effort
- **AND** the API key enforces reasoning effort `high`
- **THEN** the persisted request log entry records `requested_reasoning_effort = null`
- **AND** the persisted request log entry records effective `reasoning_effort = "high"`
