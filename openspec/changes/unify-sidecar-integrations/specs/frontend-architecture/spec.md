## ADDED Requirements

### Requirement: Sidecar integrations share a unified settings card

The Settings page SHALL render the CLIProxyAPI, OpenRouter, and OmniRoute integrations using a single shared sidecar integration component composed of the same field set: an enable toggle, a base URL field, an API key field, a prefixes editor, a full-models editor, a collapsible discovered-models browser, request/connect timeout fields, and a model cache TTL field. The management key field SHALL appear only for CLIProxyAPI. Each prefix entry SHALL expose a per-entry "remove prefix before forwarding" checkbox. The full-models list SHALL render outside the discovered-models browser, and selecting a discovered model or entering a full model name SHALL both add to that single list. Field copy SHALL state that full model names take precedence over prefixes across all integrations.

#### Scenario: All three integrations expose the uniform field set

- **WHEN** a user opens the Settings page
- **THEN** the CLIProxyAPI, OpenRouter, and OmniRoute sections each show enable, base URL, API key, prefixes (with per-entry strip checkbox), full models, discovered-models browser, timeouts, and cache TTL
- **AND** only the CLIProxyAPI section shows a management key field

#### Scenario: Selecting a discovered model adds it to the full-models list

- **WHEN** a user expands an integration's discovered-models browser and selects a model
- **THEN** the model is added to that integration's full-models list
- **AND** the full-models list is displayed outside the discovered-models browser

#### Scenario: Per-prefix strip checkbox is editable per entry

- **WHEN** a user toggles the strip checkbox on one prefix entry
- **THEN** only that prefix entry's strip flag changes
- **AND** saving persists the per-entry strip flags

### Requirement: Settings rejects prefixes and full models already used by another integration

The shared sidecar settings component SHALL reject adding a prefix or full model name that is already configured (as a prefix or full model) on a different integration, displaying inline red text that names the integration already using the value. A prefix string and a full model string that coincide textually across integrations SHALL be permitted, because full model names take precedence at routing time. Saving SHALL be blocked while an unresolved cross-integration conflict exists, and the backend SHALL reject a settings update that contains such a conflict with a structured error identifying the conflicting value and its owning integration.

#### Scenario: Adding a duplicate prefix is rejected inline

- **GIVEN** OpenRouter already has prefix `deepseek/`
- **WHEN** a user tries to add prefix `deepseek/` to OmniRoute
- **THEN** the add is rejected with red text naming OpenRouter as the existing owner
- **AND** the value is not added to OmniRoute

#### Scenario: Prefix and full model may coincide across integrations

- **GIVEN** OpenRouter has prefix `minimax/`
- **WHEN** a user adds full model `minimax/minimax-m3` to OmniRoute
- **THEN** the add is accepted
- **AND** no conflict is shown

#### Scenario: Backend rejects a conflicting settings update

- **WHEN** a settings update is submitted with the same prefix configured on two integrations
- **THEN** the backend rejects the update with a structured conflict error
- **AND** the error identifies the conflicting value and its owning integration
```
