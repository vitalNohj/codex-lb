## ADDED Requirements

### Requirement: Sidecar request-log rows use standard model and transport presentation

The dashboard recent-requests table MUST NOT add sidecar-specific badges or labels to the Model cell for Claude, OpenRouter, or OmniRoute sidecar request-log rows. The table MUST render the Transport cell from the request-log `transport` value using the same standard protocol labels as non-sidecar rows. The request details dialog MUST render Transport from the same standard transport value and MUST keep sidecar source identification separate in the Source field.

#### Scenario: Claude sidecar HTTP row renders like a standard HTTP row

- **WHEN** a request-log row has `source: "claude_sidecar"` and `transport: "http"`
- **THEN** the recent-requests table Model cell shows only the formatted model label plus any normal warmup or requested-tier annotations
- **AND** the Model cell does not show `Claude sidecar`
- **AND** the Transport cell shows `HTTP`
- **AND** the Transport cell does not show `Sidecar HTTP`

#### Scenario: Sidecar source remains available in request details

- **WHEN** a user opens request details for a sidecar request-log row
- **THEN** the details Transport field shows the standard transport label
- **AND** the details Source field shows the sidecar source label
