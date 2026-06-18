## ADDED Requirements

### Requirement: Unified sidecar routing resolves a single owner per model

The service SHALL decide sidecar routing for `POST /v1/chat/completions` through a single provider-agnostic resolver shared by all sidecar integrations (CLIProxyAPI/`claude_sidecar`, OpenRouter, OmniRoute). The resolver SHALL evaluate only enabled integrations and SHALL return at most one routing decision consisting of the owning integration and the wire model to forward; when no integration matches, the request SHALL follow the existing chat-completions-to-Responses path.

Resolution SHALL proceed in two passes:
1. **Full model name pass:** if the effective model exactly matches (case-insensitive) an entry in any enabled integration's full-model list, that integration owns the request and the wire model SHALL equal the effective model unchanged (no prefix stripping).
2. **Prefix pass:** otherwise, if the effective model matches a configured prefix of any enabled integration, the integration owning the longest matching prefix owns the request; the matched prefix SHALL be removed from the wire model when that prefix's strip flag is set, and SHALL be left unchanged otherwise.

When two integrations would otherwise tie within a pass (which cross-integration uniqueness prevents), the resolver SHALL break the tie deterministically in the order CLIProxyAPI, then OpenRouter, then OmniRoute. The resolver SHALL run after API-key enforced-model resolution and model-access validation, and SHALL be applied before any Codex account selection, sticky sessions, or upstream transport selection.

#### Scenario: Full model name beats a prefix on another integration

- **GIVEN** OpenRouter is enabled with prefix `minimax/`
- **AND** OmniRoute is enabled with full model `minimax/minimax-m3`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "minimax/minimax-m3"`
- **THEN** the request is routed to OmniRoute
- **AND** the forwarded payload includes `model: "minimax/minimax-m3"` unchanged
- **AND** OpenRouter receives no request

#### Scenario: Prefix match routes when no full model matches

- **GIVEN** OpenRouter is enabled with prefix `minimax/`
- **AND** no integration has a full model equal to `minimax/minimax-other`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "minimax/minimax-other"`
- **THEN** the request is routed to OpenRouter

#### Scenario: Longest matching prefix owns the request

- **GIVEN** integration A is enabled with prefix `cp-`
- **AND** integration B is enabled with prefix `cp-deep-`
- **AND** no integration has a matching full model
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "cp-deep-foo"`
- **THEN** the request is routed to integration B

#### Scenario: No match falls through to the Codex path

- **GIVEN** all enabled integrations' prefixes and full models exclude `gpt-5.4`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "gpt-5.4"`
- **THEN** the service uses the existing chat-completions-to-Responses mapping path
- **AND** no sidecar receives the request

#### Scenario: Disabled integrations are not considered

- **GIVEN** OmniRoute is disabled and its full-model list includes `my-model`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "my-model"`
- **THEN** OmniRoute receives no request
- **AND** the request follows the existing validation and upstream path

### Requirement: Per-prefix strip controls wire model rewriting

Each configured prefix on a sidecar integration SHALL carry an explicit strip flag. When the unified resolver routes a request by a prefix whose strip flag is true, the matched prefix SHALL be removed from the forwarded wire model. When the strip flag is false, the wire model SHALL retain the prefix. A request routed by a full model name SHALL never have any text removed, even when a configured prefix on any integration is a textual substring of the model name.

For sidecar requests, API-key validation, request-limit reservations, and request logs SHALL use the effective model requested by the client, not the stripped wire model.

#### Scenario: Strip-enabled prefix is removed from the wire model

- **GIVEN** CLIProxyAPI is enabled with prefix `cp-` and strip enabled
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "cp-claude-sonnet-4"`
- **THEN** CLIProxyAPI receives a payload with `model: "claude-sonnet-4"`
- **AND** the request log records the effective model `cp-claude-sonnet-4`

#### Scenario: Strip-disabled prefix is preserved in the wire model

- **GIVEN** OpenRouter is enabled with prefix `deepseek/` and strip disabled
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "deepseek/deepseek-chat"`
- **THEN** OpenRouter receives a payload with `model: "deepseek/deepseek-chat"`

#### Scenario: Full model match is never stripped despite a matching prefix

- **GIVEN** an integration is enabled with prefix `cp-` and strip enabled
- **AND** the same integration has full model `cp-deepseek-special`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "cp-deepseek-special"`
- **THEN** the integration receives a payload with `model: "cp-deepseek-special"` unchanged
```
