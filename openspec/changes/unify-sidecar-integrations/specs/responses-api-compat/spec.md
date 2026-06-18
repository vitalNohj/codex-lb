## ADDED Requirements

### Requirement: Responses-shaped requests use the unified sidecar resolver

For Responses-shaped requests handled by the public `/v1/responses` and `/backend-api/codex` paths, the service SHALL determine sidecar ownership using the same unified resolver and precedence as chat completions (full-model exact match before longest-prefix match, evaluated across all enabled integrations). When the resolver selects a sidecar that supports Responses dispatch, the request SHALL be translated to that sidecar's chat-completions form and its output translated back to the Responses contract; when no integration matches, the request SHALL follow the existing Responses upstream path.

The wire model forwarded to the sidecar SHALL follow the same per-prefix strip and full-model-as-is rules as chat completions, and API-key validation, reservations, and request logs SHALL use the effective requested model.

#### Scenario: Full model name routes a Responses request to its owner

- **GIVEN** OmniRoute is enabled with full model `minimax/minimax-m3`
- **WHEN** a client sends a Responses-shaped request with `model: "minimax/minimax-m3"`
- **THEN** the request is dispatched to OmniRoute
- **AND** the forwarded chat payload includes `model: "minimax/minimax-m3"` unchanged
- **AND** the response is returned in the Responses contract

#### Scenario: Strip-enabled prefix rewrites the Responses wire model

- **GIVEN** an integration that supports Responses dispatch is enabled with prefix `cp-` and strip enabled
- **WHEN** a client sends a Responses-shaped request with `model: "cp-some-model"`
- **THEN** the sidecar receives a chat payload with `model: "some-model"`
- **AND** the request log records the effective model `cp-some-model`

#### Scenario: No sidecar match keeps the Responses upstream path

- **GIVEN** all enabled integrations' prefixes and full models exclude `gpt-5.4`
- **WHEN** a client sends a Responses-shaped request with `model: "gpt-5.4"`
- **THEN** the service uses the existing Responses upstream path
- **AND** no sidecar receives the request
```
