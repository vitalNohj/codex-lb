## ADDED Requirements

### Requirement: Sidecar request-log rows use standard model and transport presentation

The dashboard recent-requests table MUST NOT add sidecar-specific badges or labels to the Model cell for Claude, OpenRouter, or OmniRoute sidecar request-log rows. The table MUST render the Transport cell from the request-log `transport` value using the same standard protocol labels as non-sidecar rows. The Account cell MUST render Claude sidecar rows as `CLIProxyAPI: <auth label>` when the request-log API provides sidecar auth identity and as `CLIProxyAPI` when it does not. The Account cell MUST render OpenRouter and OmniRoute sidecar rows as `OpenRouter` and `OmniRoute`, without the word `sidecar`. The request details dialog MUST render Transport from the same standard transport value and MUST keep sidecar source identification separate in the Source field.

#### Scenario: Claude sidecar HTTP row renders like a standard HTTP row

- **WHEN** a request-log row has `source: "claude_sidecar"` and `transport: "http"`
- **THEN** the recent-requests table Model cell shows only the formatted model label plus any normal warmup or requested-tier annotations
- **AND** the Model cell does not show `Claude sidecar`
- **AND** the Transport cell shows `HTTP`
- **AND** the Transport cell does not show `Sidecar HTTP`

#### Scenario: Sidecar account labels omit sidecar wording

- **WHEN** the recent-requests table renders OpenRouter and OmniRoute sidecar request-log rows
- **THEN** the Account cells show `OpenRouter` and `OmniRoute`
- **AND** the Account cells do not show `OpenRouter sidecar` or `OmniRoute sidecar`

#### Scenario: Claude sidecar account label includes auth identity when available

- **WHEN** a Claude sidecar request-log row includes `sidecarAccountLabel: "claude@example.com"`
- **THEN** the Account cell shows `CLIProxyAPI: claude@example.com`

#### Scenario: Sidecar source remains available in request details

- **WHEN** a user opens request details for a sidecar request-log row
- **THEN** the details Transport field shows the standard transport label
- **AND** the details Source field shows the sidecar source label
