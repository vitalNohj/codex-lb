# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Replace a CLIProxyAPI account excluded-models list

codex-lb MUST let an operator replace the whole model-exclusion list on a single CLIProxyAPI Claude account by forwarding the auth-file `name` and a list of model patterns to CLIProxyAPI's `PATCH /v0/management/auth-files/fields` endpoint as the `excluded_models` field, keeping CLIProxyAPI auth files as the only source of truth and attempting to refresh live routing state after a successful update. A confirmed write MUST also return `savedAccount` with the normalized list and `excludedModelsState="available"`, even if the subsequent routing read fails. The submitted list MUST be normalized before it is sent: entries are trimmed, blank entries and entries containing a newline, NUL, or comma are dropped, entries longer than 128 characters are dropped, duplicates are removed case-insensitively keeping the first spelling, at most 32 entries are kept, and the remaining order is preserved. A comma MUST be rejected because CLIProxyAPI stores this list as a comma-joined attribute and splits it on `,` when routing, so an embedded comma would split one pattern into two.

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

codex-lb MUST expose each Claude account's live model-exclusion list as an `excludedModels` string array in the routing response (`GET /api/claude-sidecar/routing`) and in sidecar auth account rows returned by the quota endpoint and the accounts list, so the Settings routing section, the Accounts tab, and the dashboard account card can render the exclusions per account. Routing reads MUST use the listing's exclusion field when present, falling back to the auth file named by the listing entry's `path` when absent. Quota, Accounts, and Dashboard auth rows MUST re-read that file for each response rather than treating persisted snapshot exclusions as authoritative confirmation after an uncertain write. File reads MUST copy only the `excluded_models` (or `excluded-models`) key. Credential material from that file, including access and refresh tokens, MUST NOT appear in any dashboard response or log line.

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
- **THEN** codex-lb reports `excludedModelsState="unreadable"` and an empty `excludedModels` for that account
- **AND** codex-lb does not read or log the contents of that path

#### Scenario: Sidecar auth rows include the exclusion list

- **GIVEN** the Claude sidecar quota snapshot identifies an account whose auth file excludes one model pattern
- **WHEN** an operator requests the accounts list or the Claude sidecar quota endpoint
- **THEN** that account's sidecar auth row reports that pattern in `excludedModels`

#### Scenario: Credential material is not disclosed

- **GIVEN** an auth file containing both an `excluded_models` list and token fields
- **WHEN** codex-lb returns routing, quota, or accounts responses for that account
- **THEN** the response contains the exclusion list
- **AND** the response contains no field from that auth file other than the exclusion list

### Requirement: Report whether an account's excluded-models list could be read

codex-lb MUST report an `excludedModelsState` of `available`, `unreadable`, or `unsupported` alongside `excludedModels` everywhere the list is exposed (routing response, quota endpoint, accounts list), and reads MUST be fail-closed so that an unread list is never presented as an empty one. `available` means the list was read verbatim from CLIProxyAPI and MAY be edited and saved back. `unreadable` means the read failed - no auth-file path, a path outside the CLIProxyAPI auth directory, a missing or unparsable file, a value that is not a list of strings, or a list that normalization would not leave unchanged - and editing MUST be locked with the failure surfaced, because a whole-list save of the list shown would overwrite the real exclusions. `unsupported` means the row has no CLIProxyAPI auth file to edit at all; editing MUST be unavailable but MUST NOT be presented as a failure. An absent exclusion key, or one whose value is JSON `null`, is a successful read of an empty list and MUST report `available`.

#### Scenario: A readable list is editable

- **GIVEN** an auth file inside the CLIProxyAPI auth directory whose `excluded_models` list is already normalized
- **WHEN** codex-lb reports that account
- **THEN** `excludedModelsState` is `available`
- **AND** `excludedModels` is that list verbatim

#### Scenario: A cleared list stored as null reads as an available empty list

- **GIVEN** an auth file whose `excluded_models` value is JSON `null`
- **WHEN** codex-lb reports that account
- **THEN** `excludedModelsState` is `available`
- **AND** `excludedModels` is empty

#### Scenario: A list that normalization would change is unreadable

- **GIVEN** an auth file whose `excluded_models` list holds more entries than the cap, an over-length pattern, a comma-containing pattern, or a non-string entry
- **WHEN** codex-lb reports that account
- **THEN** `excludedModelsState` is `unreadable`
- **AND** codex-lb does not offer the normalized copy as the account's list

#### Scenario: A quota snapshot persisted before the availability key decodes as unreadable

- **GIVEN** a persisted Claude sidecar quota snapshot with no `excluded_models_available` key
- **WHEN** codex-lb decodes that snapshot
- **THEN** its decoded `excluded_models_available` is false
- **AND** response read availability is determined by the authoritative read, not by that legacy snapshot

#### Scenario: A row with no CLIProxyAPI auth file is unsupported

- **GIVEN** a sidecar account row synthesized from usage estimates rather than a CLIProxyAPI auth file
- **WHEN** codex-lb reports that row
- **THEN** `excludedModelsState` is `unsupported`
- **AND** the row is not reported as a read failure

### Requirement: Order exclusion snapshot publication against saves

codex-lb MUST serialize exclusion saves and snapshot publication using the shared exclusion write lock, preserving CLIProxyAPI auth JSON as the source of truth without a persistent generation counter or desired copy. The poller MUST re-read exclusion fields from disk while holding that lock through the database commit. Pause snapshot patches MUST also hold the lock so they cannot republish older exclusions. Batched filesystem reads MUST run off the async event loop without releasing the publication lock.

#### Scenario: A save arrives during the poller's final database wait

- **GIVEN** a poll holds the exclusion lock after re-reading the auth file
- **WHEN** an exclusion save arrives while the poll awaits its snapshot database update
- **THEN** publication and the save are serialized through commit
- **AND** the older poll cannot overwrite the newer saved exclusions

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
