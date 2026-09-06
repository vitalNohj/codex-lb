# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Replace a CLIProxyAPI account excluded-models list

codex-lb MUST let an operator replace the whole model-exclusion list on a single CLIProxyAPI Claude account by forwarding the auth-file `name` and a list of model patterns to CLIProxyAPI's `PATCH /v0/management/auth-files/fields` endpoint as the `excluded_models` field, keeping CLIProxyAPI auth files as the only source of truth and returning the fresh live routing state after a successful update. The submitted list MUST be normalized before it is sent: entries are trimmed, blank entries and entries containing a newline, NUL, or comma are dropped, entries longer than 128 characters are dropped, duplicates are removed case-insensitively keeping the first spelling, at most 32 entries are kept, and the remaining order is preserved. A comma MUST be rejected because CLIProxyAPI stores this list as a comma-joined attribute and splits it on `,` when routing, so an embedded comma would split one pattern into two.

#### Scenario: Setting an exclusion list succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/excluded-models` with `name="claude-a@example.com.json"` and `excludedModels=["claude-demo-*", "claude-other-5*"]`
- **THEN** codex-lb calls `PATCH /v0/management/auth-files/fields` with that `name` and `excluded_models=["claude-demo-*", "claude-other-5*"]`
- **AND** codex-lb responds with the refreshed routing state

#### Scenario: Clearing an exclusion list succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** the auth file `claude-a@example.com.json` currently excludes one model pattern
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/excluded-models` with that `name` and `excludedModels=[]`
- **THEN** codex-lb calls `PATCH /v0/management/auth-files/fields` with that `name` and `excluded_models=[]`
- **AND** codex-lb responds with the refreshed routing state

#### Scenario: Exclusion update without management key reports precondition

- **GIVEN** CLIProxyAPI routing is enabled
- **AND** no CLIProxyAPI Management API key is configured in codex-lb settings
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/excluded-models`
- **THEN** codex-lb responds with `status="not_configured"`
- **AND** no CLIProxyAPI Management API request is made

#### Scenario: Unknown auth-file name is surfaced

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns HTTP 404 for the requested auth-file name
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/excluded-models` with that name
- **THEN** codex-lb responds with `status="error"`
- **AND** the response message indicates that the account was not found

### Requirement: Report CLIProxyAPI account excluded-models

codex-lb MUST expose each Claude account's live model-exclusion list as an `excludedModels` string array in the routing response (`GET /api/claude-sidecar/routing`) and in sidecar auth account rows returned by the quota endpoint and the accounts list, so the Settings routing section, the Accounts tab, and the dashboard account card can render the exclusions per account. When the CLIProxyAPI auth-files listing omits the field, codex-lb MUST read it from the auth file named by the listing entry's `path`, copying only the `excluded_models` (or `excluded-models`) key. Credential material from that file, including access and refresh tokens, MUST NOT appear in any dashboard response or log line.

#### Scenario: Routing response includes the exclusion list

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI reports one auth file excluding one model pattern and one auth file with no exclusions
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** the first account is reported with that pattern in `excludedModels`
- **AND** the second account is reported with an empty `excludedModels`

#### Scenario: Exclusion list is read from the auth file when the listing omits it

- **GIVEN** the CLIProxyAPI auth-files listing entry carries a `path` but no exclusion field
- **AND** the file at that path is inside the CLIProxyAPI auth directory and contains an `excluded_models` list
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** that account is reported with the exclusion list from the file

#### Scenario: Auth-file path outside the auth directory is refused

- **GIVEN** a CLIProxyAPI auth-files listing entry whose `path` resolves outside the CLIProxyAPI auth directory
- **WHEN** codex-lb resolves that account's exclusion list
- **THEN** codex-lb reports an empty `excludedModels` for that account
- **AND** codex-lb does not read or log the contents of that path

#### Scenario: Sidecar auth rows include the exclusion list

- **GIVEN** the Claude sidecar quota snapshot contains an account excluding one model pattern
- **WHEN** an operator requests the accounts list or the Claude sidecar quota endpoint
- **THEN** that account's sidecar auth row reports that pattern in `excludedModels`

#### Scenario: Credential material is not disclosed

- **GIVEN** an auth file containing both an `excluded_models` list and token fields
- **WHEN** codex-lb returns routing, quota, or accounts responses for that account
- **THEN** the response contains the exclusion list
- **AND** the response contains no field from that auth file other than the exclusion list

### Requirement: Excluded models are not account-specific code

The codex-lb backend MUST treat the exclusion list as opaque operator data and MUST NOT special-case any account email, any specific model name, or any model family when accepting, storing, or reporting it. Any pattern string that survives normalization MUST be accepted, and removing an entry MUST require no code change.

#### Scenario: An arbitrary pattern is accepted

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/excluded-models` with a pattern the backend has never seen before
- **THEN** codex-lb forwards that pattern unchanged to CLIProxyAPI
- **AND** codex-lb applies no per-account or per-model branch while doing so

#### Scenario: Reversing an exclusion needs no deployment

- **GIVEN** an account whose exclusion list contains one pattern
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/excluded-models` for that account without that pattern
- **THEN** codex-lb removes it from the CLIProxyAPI auth file
- **AND** that account becomes eligible again for the matching models with no codex-lb code or configuration change
