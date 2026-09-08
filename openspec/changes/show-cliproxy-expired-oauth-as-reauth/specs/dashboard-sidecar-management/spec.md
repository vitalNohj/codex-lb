# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Expired Claude OAuth access tokens are reauth_required

Codex-lb MUST set each Claude sidecar auth row's `status` to `reauth_required` when the credential's OAuth access-token expiry is in the past, or when CLIProxyAPI already reports an auth-death shape (`invalid_grant`, `authentication_error`, `re-authenticate`, or `unavailable` plus `unauthorized`).

#### Scenario: Past access-token expiry shows Re-auth required

- **GIVEN** a Claude auth file whose `expired` timestamp is in the past
- **AND** CLIProxyAPI still lists that file as `status=active` and `unavailable=false`
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is `reauth_required`

#### Scenario: Unexpired access token does not show Re-auth required

- **GIVEN** a Claude auth file whose `expired` timestamp is in the future
- **AND** no auth-death status message is present
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is not `reauth_required`

#### Scenario: Missing expiry does not invent a badge

- **GIVEN** a Claude auth file with no `expired` field
- **AND** CLIProxyAPI reports `status=active` and `unavailable=false`
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` remains `active`

#### Scenario: Quota cooldown is not re-auth

- **GIVEN** a Claude auth whose access token is unexpired
- **AND** CLIProxyAPI reports quota exceeded or rate limited
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is not `reauth_required`

### Requirement: Auth-file expiry reads never expose tokens

Codex-lb MUST read only the `expired` (or `expires_at`) field when filling expiry from a Claude auth JSON on disk, MUST refuse paths outside the CLIProxyAPI auth directory, and MUST NOT include access or refresh token values in the quota snapshot or account summary.

#### Scenario: Disk read returns expiry only

- **GIVEN** an auth-files list entry with a `path` under the CLIProxyAPI auth directory
- **AND** the file JSON contains `expired` plus token fields
- **WHEN** quota parsing fills expiry from disk
- **THEN** the parsed account has that `expired` timestamp
- **AND** the parsed account and serialized snapshot do not contain `access_token` or `refresh_token`
