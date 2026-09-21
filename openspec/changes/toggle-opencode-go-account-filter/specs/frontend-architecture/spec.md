## ADDED Requirements

### Requirement: Dashboard account-type filter covers OpenCode Go

The dashboard account-type visibility filter MUST expose an `opencode_go` key labeled `OpenCode Go`, rendered after OrcaRouter, after OmniRoute when that filter is shown, and before OpenAI-compat. It MUST default to visible, including when hydrating a persisted preference written before the key existed, and MUST NOT reset the other stored toggles while filling it in.

#### Scenario: OpenCode Go accounts have their own toggle

- **GIVEN** the dashboard renders a synthetic account with `provider: "opencode_go"`
- **WHEN** the operator turns the OpenCode Go account-type toggle off
- **THEN** that account is removed from the rendered accounts
- **AND** the other account types stay visible

#### Scenario: Turning the toggle back on shows the account

- **GIVEN** the OpenCode Go account-type toggle is off
- **WHEN** the operator turns it on
- **THEN** the synthetic account with `provider: "opencode_go"` is rendered again
