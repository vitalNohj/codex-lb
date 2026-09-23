## ADDED Requirements

### Requirement: Claude strip-prefix aliases appear on the models list

`GET /v1/models` MUST list a Claude sidecar strip-prefix alias when dispatch of that alias returns the upstream model id the alias names. The listed id MUST be the strip prefix plus that upstream id, including each `-`/`_` prefix variant. An alias whose dispatch rewrites the upstream id MUST stay out of the catalog. A discovered id that does not itself route MUST stay out of the catalog as a bare id.

#### Scenario: Opus 5.5 cc/ alias is listed

- **GIVEN** CLIProxyAPI lists `claude-opus-5-5` and the Claude prefix `cc/` strips
- **WHEN** a client calls `GET /v1/models`
- **THEN** the catalog includes `cc/claude-opus-5-5`

#### Scenario: Chat with the alias forwards the named upstream id

- **WHEN** a client calls `/v1/chat/completions` with model `cc/claude-opus-5-5`
- **THEN** the forwarded model is `claude-opus-5-5`

#### Scenario: Rewritten suffix alias is omitted

- **GIVEN** CLIProxyAPI lists `claude-opus-4-7-high` and the Claude prefix `cc/` strips
- **WHEN** a client calls `GET /v1/models`
- **THEN** the catalog does not include `cc/claude-opus-4-7-high`
