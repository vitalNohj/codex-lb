## ADDED Requirements

### Requirement: Discovery lists only models a key-required integration can serve

When serving `GET /v1/models` or the dashboard `GET /api/models`, the system
SHALL list OrcaRouter and OpenRouter models, and fetch those integrations'
upstream model catalogs, only when the integration is enabled and has a usable
API key. A usable key is one that is set, decrypts, and is not blank. On
`GET /v1/models` the system MUST omit a model alias whose every target that is
visible for the requesting API key is owned by an OrcaRouter, OpenRouter, or
OpenCode Go integration without a usable key. Routing ownership MUST NOT change:
an enabled integration without a key still owns its models, so a request for one
is refused locally and is not sent to another provider.

#### Scenario: A keyless integration is not advertised

- **GIVEN** OrcaRouter and OpenRouter are enabled with no API key
- **AND** `pooled/glm-5.3` has targets `["orcarouter/z-ai/glm-5.3", "z-ai/glm-5.3"]`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes neither target nor `pooled/glm-5.3`
- **AND** neither upstream receives a request

#### Scenario: A pool alias stays listed while one target is usable

- **GIVEN** the same pool, OrcaRouter with no API key, and OpenRouter with one
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response includes `z-ai/glm-5.3` and `pooled/glm-5.3`
- **AND** the response does not include `orcarouter/z-ai/glm-5.3`

#### Scenario: The dashboard picker does not poll a keyless integration

- **GIVEN** OrcaRouter and OpenRouter are enabled with no API key
- **WHEN** the dashboard calls `GET /api/models`
- **THEN** neither upstream receives a request
