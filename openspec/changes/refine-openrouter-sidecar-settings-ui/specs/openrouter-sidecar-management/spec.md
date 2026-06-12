## ADDED Requirements

### Requirement: Dashboard settings expose OpenRouter model discovery

The dashboard OpenRouter sidecar settings section MUST show the discovered model count and MUST let an authenticated operator search the full discovered model list client-side. Each discovered model MUST offer an action that adds its provider prefix (the model ID through the first `/`) to the configured model prefixes. The dashboard MUST NOT fetch the OpenRouter model list while the sidecar is disabled or no API key is configured.

#### Scenario: Operator searches discovered OpenRouter models in Settings

- **GIVEN** the OpenRouter sidecar is enabled with a configured API key
- **AND** the dashboard model list endpoint returns multiple models with different provider prefixes
- **WHEN** the operator types a provider name into the model search field
- **THEN** only models whose IDs contain the search text remain visible
- **AND** the section header still shows the total discovered model count

#### Scenario: Operator adds a provider prefix from a discovered model

- **GIVEN** the discovered model list shows `deepseek/deepseek-chat`
- **WHEN** the operator activates the add-prefix action for that model
- **THEN** `deepseek/` is appended to the model prefixes input without duplicates
