## ADDED Requirements

### Requirement: CLIProxyAPI models advertise the limits CLIProxyAPI publishes

When serving `GET /v1/models`, the system SHALL read CLIProxyAPI's Codex-client model catalog (`GET /v1/models?client_version=...` on the Claude sidecar) and use the `context_window` and `max_tokens` it publishes for the upstream id each Claude-sidecar entry names. A row MUST count as published only when both values are positive integers. When an output limit is published, `max_output_tokens`, `maxOutputTokens` and `capabilities.max_output_tokens` MUST carry it; otherwise they MUST be absent.

#### Scenario: Grok models advertise their published 500k window

- **GIVEN** CLIProxyAPI lists `grok-4.7` and `grok-4.7-build-fast`, its catalog publishes `context_window=500000` and `max_tokens=500000` for both, and `cc/` is a strip prefix
- **WHEN** a client calls `GET /v1/models`
- **THEN** `cc/grok-4.7` and `cc/grok-4.7-build-fast` report `context_length=500000` and `max_output_tokens=500000`

#### Scenario: Auth-prefixed ids use their own row

- **GIVEN** CLIProxyAPI lists `lb5dc882f41e/grok-4.7` and its catalog publishes `context_window=500000` for that slug
- **WHEN** a client calls `GET /v1/models`
- **THEN** `cc/lb5dc882f41e/grok-4.7` reports `context_length=500000`

#### Scenario: Placeholder catalog window is not published

- **GIVEN** the catalog row for `grok-imagine-image` has `context_window=272000` and no `max_tokens`
- **WHEN** a client calls `GET /v1/models`
- **THEN** `cc/grok-imagine-image` reports `context_length=200000` and has no `max_output_tokens`

### Requirement: Override, then CLIProxyAPI, then the existing fallbacks

The system SHALL resolve a Claude-sidecar entry's advertised window in this order: the operator's context window override for the advertised id; the CLIProxyAPI-published window; the Claude sidecar published window table; the provider catalog entry; 200000.

#### Scenario: CLIProxyAPI wins over the static Claude table

- **GIVEN** the catalog publishes `context_window=200000` and `max_tokens=64000` for `claude-sonnet-4-6`
- **WHEN** a client calls `GET /v1/models`
- **THEN** `cc/claude-sonnet-4-6` reports `context_length=200000`

#### Scenario: Operator override still wins

- **GIVEN** a dashboard context window override maps `cc/grok-3-mini` to `64000` and the catalog publishes `131072`
- **WHEN** a client calls `GET /v1/models`
- **THEN** `cc/grok-3-mini` reports `context_length=64000`

### Requirement: The CLIProxyAPI catalog never degrades the listing

The system SHALL cache the catalog limits per sidecar endpoint for the models cache TTL. On a failed, timed-out or unusable catalog response it MUST keep the last good limits, or with none serve the listing with the windows it would have had without the catalog. The catalog MUST NOT change which models are listed.

#### Scenario: Catalog failure keeps the listing

- **GIVEN** the catalog request times out and no limits were fetched before
- **WHEN** a client calls `GET /v1/models`
- **THEN** every listed CLIProxyAPI model is still listed with the window it would have had without the catalog
