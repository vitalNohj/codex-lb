# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Ingest all CLIProxyAPI auth files with provider classification

codex-lb MUST ingest every CLIProxyAPI Management API auth-file entry that has a usable auth-file `name` into the CLIProxyAPI quota snapshot and routing account list, and MUST NOT drop entries solely because `provider` or `type` is not Claude. For each ingested entry, codex-lb MUST normalize and persist a provider identifier derived from the upstream auth-file fields (falling back to `unknown` when absent) so downstream adapters and UI can classify the credential.

#### Scenario: Claude and Grok auth files both appear in quota snapshot

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns auth files for a Claude OAuth account and an xAI/Grok OAuth account
- **WHEN** the CLIProxyAPI quota poller refreshes the snapshot
- **THEN** both auth files are present in the snapshot
- **AND** each entry exposes its auth-file `name`, optional `authIndex`, optional account email/label, `priority`, `disabled`/paused state, and normalized `provider`

#### Scenario: Unknown provider auth file is retained

- **GIVEN** CLIProxyAPI returns an auth file whose `provider` and `type` are unrecognized
- **AND** the auth file has a usable `name`
- **WHEN** the quota snapshot is built
- **THEN** the auth file is retained with normalized provider `unknown`
- **AND** the entry remains eligible for pause and priority controls

#### Scenario: Claude-only filter is not applied

- **GIVEN** CLIProxyAPI returns only non-Claude auth files
- **WHEN** an operator requests routing or quota state for CLIProxyAPI
- **THEN** those non-Claude auth files are returned
- **AND** the response is not an empty Claude-filtered list

### Requirement: Expose one global CLIProxyAPI routing pool across providers

codex-lb MUST expose CLIProxyAPI routing strategy and per-auth priority/pause state as one global pool spanning all ingested auth providers. `GET /api/claude-sidecar/routing` MUST include every ingested auth account (not Claude-only), and priority/pause updates MUST continue to target auth-file `name` through the existing Management API field patch endpoints without requiring a provider-specific control path.

#### Scenario: Routing list includes mixed providers

- **GIVEN** CLIProxyAPI returns Claude and Grok auth files with priorities
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** the response status is `healthy` when upstream reads succeed
- **AND** the account list includes both providers
- **AND** each account includes `name`, normalized `provider`, numeric `priority`, and paused/disabled state

#### Scenario: Priority update works for a Grok auth file

- **GIVEN** a Grok/xAI auth file `name` exists in CLIProxyAPI
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/priority` for that `name` with a numeric priority
- **THEN** codex-lb PATCHes CLIProxyAPI `auth-files/fields` with that `name` and `priority`
- **AND** the refreshed routing state includes the updated priority for that account

#### Scenario: Pause update works for a Grok auth file

- **GIVEN** a Grok/xAI auth file `name` exists in CLIProxyAPI
- **WHEN** an operator pauses or resumes that account through the existing CLIProxyAPI pause API
- **THEN** codex-lb PATCHes the auth file `disabled` field for that `name`
- **AND** Dashboard/Settings views for that auth reflect the new paused state

#### Scenario: Strategy remains a single global setting

- **GIVEN** mixed-provider auth files exist
- **WHEN** an operator sets strategy to `fill_first` or `round_robin`
- **THEN** codex-lb updates the single CLIProxyAPI routing strategy endpoint
- **AND** codex-lb does not maintain a per-provider strategy override

### Requirement: Use provider adapters for CLIProxyAPI usage observation

codex-lb MUST resolve a provider adapter for each ingested CLIProxyAPI auth account and MUST obtain live usage percentages and declared quota windows only through that adapter. The Claude adapter MUST continue to use the existing Anthropic OAuth usage path. Non-Claude adapters MUST NOT call the Anthropic OAuth usage endpoint. When a provider adapter cannot derive live limits, codex-lb MUST support manual auth-plan / quota-estimation inputs for that auth identity using the same operator workflow shape already used for Claude accounts.

#### Scenario: Claude auth still uses Anthropic OAuth usage

- **GIVEN** a Claude CLIProxyAPI auth account with OAuth credentials available through the Management API passthrough
- **WHEN** quota polling attaches live usage
- **THEN** the Claude adapter may fetch Anthropic OAuth usage
- **AND** five-hour and weekly windows remain available for that account when OAuth data is present

#### Scenario: Non-Claude auth skips Anthropic OAuth usage

- **GIVEN** a Grok/xAI CLIProxyAPI auth account
- **WHEN** quota polling attaches live usage
- **THEN** codex-lb does not call the Anthropic OAuth usage URL for that account
- **AND** any live windows come only from the Grok/xAI adapter (or none if unsupported)

#### Scenario: Manual auth-plan fallback for Grok when live limits are unavailable

- **GIVEN** a Grok/xAI auth account with no live usage source configured or discovered
- **AND** an operator saved a manual auth-plan / estimation budget for that auth identity
- **WHEN** dashboard usage estimates are built for that account
- **THEN** codex-lb uses the manual plan inputs for that auth
- **AND** the Claude auth-plan entries for other accounts remain unchanged

#### Scenario: Adapter declares which quota windows exist

- **GIVEN** provider adapters declare zero or more of `five_hour` and `weekly` windows
- **WHEN** a CLIProxyAPI auth summary is produced for Dashboard consumption
- **THEN** the summary includes only the windows declared by that account's adapter (plus manual-estimate windows when applicable)
- **AND** a weekly-only provider does not invent a five-hour live window

### Requirement: Keep one CLIProxyAPI integration for Grok routing configuration

codex-lb MUST route Grok/xAI (and future CLIProxyAPI provider) models through the existing CLIProxyAPI sidecar integration configuration (base URL, API key, management key, prefixes, full-models, effort override) and MUST NOT require a second External Integrations entry pointing at the same CLIProxyAPI instance for multi-provider auth support.

#### Scenario: Grok model uses CLIProxyAPI sidecar settings

- **GIVEN** CLIProxyAPI sidecar routing is enabled
- **AND** the CLIProxyAPI integration prefixes or full-models include a Grok/xAI model id
- **WHEN** a client sends a chat-completions request for that model
- **THEN** the request is dispatched through the existing CLIProxyAPI sidecar path
- **AND** no separate Grok integration settings object is required

#### Scenario: Prefix uniqueness still enforced

- **GIVEN** an operator attempts to add a CLIProxyAPI prefix that collides with OpenRouter, OmniRoute, or Ollama
- **WHEN** settings validation runs
- **THEN** the collision is rejected by the existing global uniqueness rules
- **AND** no automatic seed bypasses those rules

### Requirement: Preserve CLIProxyAPI request-log source without provider-qualified Account text

codex-lb MUST continue to persist CLIProxyAPI-proxied requests with the existing sidecar request-log source key used for this integration, and MUST resolve Account display identity to the correlated auth account label/email without embedding a Claude or Grok provider qualifier in that Account label string. Correlation MAY continue to use usage-queue proximity and MAY read usage-event `provider` for internal matching, but the operator-facing Account label MUST remain `CLIProxyAPI: <account>` when an account label is known and `CLIProxyAPI` when correlation misses.

#### Scenario: Correlated Grok request log account label

- **GIVEN** a CLIProxyAPI-proxied Grok request log correlates to a usage event for auth email `grok-user@example.com`
- **WHEN** request logs are listed for the dashboard
- **THEN** the Account label is `CLIProxyAPI: grok-user@example.com`
- **AND** the Account label does not contain `Grok` or `xAI` as a qualifier

#### Scenario: Correlated Claude request log account label unchanged in shape

- **GIVEN** a CLIProxyAPI-proxied Claude request log correlates to auth email `claude-user@example.com`
- **WHEN** request logs are listed for the dashboard
- **THEN** the Account label is `CLIProxyAPI: claude-user@example.com`
- **AND** the Account label does not contain `Claude` as a qualifier

#### Scenario: Correlation miss stays bare CLIProxyAPI

- **GIVEN** a CLIProxyAPI-proxied request log has no usage-event match within the correlation window
- **WHEN** request logs are listed for the dashboard
- **THEN** the Account label is `CLIProxyAPI`
