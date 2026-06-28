## ADDED Requirements

### Requirement: Request logs distinguish requested and effective reasoning effort

When a request log entry includes reasoning-effort data, the dashboard request-log API response MUST expose the requested reasoning effort and the effective reasoning effort separately. The recent-requests UI MUST display the effective reasoning effort when available and MUST also show the requested reasoning effort when it differs from the visible effective effort.

#### Scenario: Dashboard shows enforced effort and requested effort

- **WHEN** a request log entry is recorded with `requested_reasoning_effort: "medium"` and effective `reasoning_effort: "xhigh"`
- **THEN** the `GET /api/request-logs` response includes `requestedReasoningEffort: "medium"` and `reasoningEffort: "xhigh"`
- **AND** the dashboard renders the model label with `xhigh`
- **AND** the dashboard also shows that the request asked for `medium`

#### Scenario: Matching efforts show only the effective value

- **WHEN** a request log entry is recorded with `requested_reasoning_effort: "high"` and effective `reasoning_effort: "high"`
- **THEN** the `GET /api/request-logs` response includes `requestedReasoningEffort: "high"` and `reasoningEffort: "high"`
- **AND** the dashboard renders the effective effort `high` without a separate requested annotation

#### Scenario: Legacy row without a requested effort still renders

- **WHEN** a request log entry has `requested_reasoning_effort: null` and effective `reasoning_effort: "xhigh"`
- **THEN** the `GET /api/request-logs` response includes `requestedReasoningEffort: null` and `reasoningEffort: "xhigh"`
- **AND** the dashboard renders the effective effort `xhigh` without a separate requested annotation
