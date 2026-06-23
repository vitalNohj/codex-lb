## ADDED Requirements

### Requirement: Request logs surface the sidecar requested reasoning effort when it differs from the effective effort

The dashboard request-log API response MUST expose the requested reasoning effort and the effective reasoning effort as separate fields. The recent-requests UI MUST display the effective reasoning effort next to the model and MUST also show the requested reasoning effort when it is present and differs from the effective effort.

#### Scenario: Sidecar override shows both efforts

- **WHEN** a sidecar request log entry is recorded with `requested_reasoning_effort: "medium"` and effective `reasoning_effort: "high"`
- **THEN** the `GET /api/request-logs` response includes `requestedReasoningEffort: "medium"` and `reasoningEffort: "high"`
- **AND** the dashboard renders the model label with `high`
- **AND** the dashboard also shows that the request asked for `medium`

#### Scenario: Matching efforts show only the effective value

- **WHEN** a request log entry is recorded with `requested_reasoning_effort: "high"` and effective `reasoning_effort: "high"`
- **THEN** the `GET /api/request-logs` response includes `requestedReasoningEffort: "high"` and `reasoningEffort: "high"`
- **AND** the dashboard renders the effective effort `high` without a separate requested annotation

#### Scenario: Legacy row without a requested effort still renders

- **WHEN** a request log entry has `requested_reasoning_effort: null` and effective `reasoning_effort: "high"`
- **THEN** the `GET /api/request-logs` response includes `requestedReasoningEffort: null` and `reasoningEffort: "high"`
- **AND** the dashboard renders the effective effort `high` without a separate requested annotation
