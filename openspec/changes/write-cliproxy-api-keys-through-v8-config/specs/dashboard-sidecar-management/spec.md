# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: API-key account writes keep every other config field

codex-lb MUST read and write CLIProxyAPI API-key accounts through the v8 config API (`/v8/management/config/api-keys`). It MUST NOT write them through the `/v0/management/<kind>-api-key` endpoints. A write MUST replace only the family being edited, built from the list just read. It MUST keep every group name, shared field, per-key field, and unknown field it did not edit.

#### Scenario: Storing a sticky prefix changes only that prefix

- **GIVEN** the CLIProxyAPI config has Claude groups `my-team-key` (one key, priority and headers) and `shared-pool` (two keys), and a Codex group `codex-main`
- **WHEN** codex-lb stores a generated prefix for every credential
- **THEN** the saved config differs from the original only by the new `prefix` values
- **AND** every group keeps its name, keys, and fields

### Requirement: API-key account writes do not overwrite concurrent changes

A write MUST send the read's `ETag` in `If-Match` when CLIProxyAPI sent one. On `412`, codex-lb MUST redo the edit on a fresh read, up to four attempts. When the v8 config API is missing, codex-lb MUST fail the write and MUST NOT fall back to a v0 write.

#### Scenario: A concurrent change is not overwritten

- **GIVEN** the config changes between codex-lb's read and its write
- **WHEN** CLIProxyAPI answers the write with `412`
- **THEN** codex-lb rereads the family and applies its edit to the fresh list

#### Scenario: A CLIProxyAPI without the v8 config API is not written

- **GIVEN** `GET /v8/management/config/api-keys` returns a non-JSON `404`
- **WHEN** an operator edits an API-key account
- **THEN** codex-lb returns an error and sends no write

### Requirement: A sticky prefix pins one credential

A prefix stored for one key of a multi-key non-compat group MUST be written on that key, so only that credential is pinned. An openai-compatibility group MUST be pinned as one unit. Changing `base-url` for one key of a multi-key group MUST move that key into its own group with a unique name. The rest of the group MUST stay unchanged.

#### Scenario: Two keys of one group get different prefixes

- **GIVEN** group `shared-pool` has two keys
- **WHEN** codex-lb stores a prefix for each key
- **THEN** each key carries its own `prefix`
- **AND** the group has no group-level `prefix`

### Requirement: Route identity survives edits

The routing identity of an API-key credential MUST be CLIProxyAPI's `auth_index`. When CLIProxyAPI does not report one, codex-lb MUST compute the same value, `hex(sha256("<seed-kind>:<base-url>+<api-key>")[:8])`. An openai-compatibility group MUST use its first key. Editing the prefix, models, name, weight, priority, or on/off switch MUST NOT change the identity.

#### Scenario: Disabling an openai-compatibility group keeps its pin

- **GIVEN** an openai-compatibility group with a stored sticky prefix
- **WHEN** an operator disables the group
- **THEN** the group's routing identity is unchanged

### Requirement: OpenAI-compatible groups expose the prompt-cache-key switch

codex-lb MUST report `supportPromptCacheKey` for openai-compatibility accounts. An update MUST write `support-prompt-cache-key` only when the request sets it. The switch MUST default to off.

#### Scenario: Turning the switch on writes only that field

- **GIVEN** an openai-compatibility group without `support-prompt-cache-key`
- **WHEN** an operator turns the switch on
- **THEN** the saved config gains `support-prompt-cache-key: true` on that group and no other change
