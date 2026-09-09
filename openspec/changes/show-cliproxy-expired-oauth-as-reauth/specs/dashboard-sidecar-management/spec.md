# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Claude OAuth credentials that cannot refresh are reauth_required

Codex-lb MUST set each Claude sidecar auth row's `status` to `reauth_required` when CLIProxyAPI reports an auth-death status message (`invalid_grant`, `unauthorized`, `authentication_error`, `re-authenticate`, `refresh token expired`, or an expired OAuth/access-token message), when it reports `unavailable` together with `status=unauthorized`, or when the credential's OAuth access-token expiry lapsed longer ago than CLIProxyAPI's proactive Claude refresh lead of 4 hours.

Codex-lb MUST NOT badge a credential whose access-token expiry lapsed within that refresh lead. CLIProxyAPI renews Claude access tokens from a background refresh loop that starts 4 hours before `expired`, so a recently lapsed persisted timestamp describes a pending or not-yet-flushed refresh, a just-restarted sidecar, or clock skew - not a credential that needs an operator login.

Codex-lb MUST NOT badge a quota-exceeded or operator-paused credential as `reauth_required`, regardless of its expiry.

#### Scenario: Long-lapsed access-token expiry shows Re-auth required

- **GIVEN** a Claude auth whose `expired` timestamp lapsed more than 4 hours ago
- **AND** CLIProxyAPI still lists that file as `status=active` and `unavailable=false`
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is `reauth_required`

#### Scenario: Recently lapsed access token is a pending refresh, not re-auth

- **GIVEN** a Claude auth whose `expired` timestamp lapsed within the last 4 hours
- **AND** no auth-death status message is present
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is unchanged and is not `reauth_required`

#### Scenario: Unexpired access token does not show Re-auth required

- **GIVEN** a Claude auth file whose `expired` timestamp is in the future
- **AND** no auth-death status message is present
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is not `reauth_required`

#### Scenario: Failed refresh shows Re-auth required before the token lapses

- **GIVEN** a Claude auth whose access token is still unexpired
- **AND** CLIProxyAPI reports `unavailable=true` with a `status_message` of `unauthorized` or `invalid_grant`
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is `reauth_required`

#### Scenario: Missing expiry does not invent a badge

- **GIVEN** a Claude auth file with no `expired` field
- **AND** CLIProxyAPI reports `status=active` and `unavailable=false`
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` remains `active`

#### Scenario: Quota cooldown is not re-auth

- **GIVEN** a Claude auth that CLIProxyAPI reports as quota exceeded or rate limited
- **AND** its access-token expiry is unexpired or already lapsed
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is not `reauth_required`

#### Scenario: Operator pause is not re-auth

- **GIVEN** an operator-paused Claude auth whose access-token expiry has lapsed
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` remains the paused status and is not `reauth_required`

### Requirement: Auth-file expiry reads never expose tokens

Codex-lb MUST read only the `expired` (or `expires_at`) field when filling expiry from a Claude auth JSON on disk, MUST refuse paths outside the CLIProxyAPI auth directory, and MUST NOT include access or refresh token values in the quota snapshot or account summary.

#### Scenario: Disk read returns expiry only

- **GIVEN** an auth-files list entry with a `path` under the CLIProxyAPI auth directory
- **AND** the file JSON contains `expired` plus token fields
- **WHEN** quota parsing fills expiry from disk
- **THEN** the parsed account has that `expired` timestamp
- **AND** the parsed account and serialized snapshot do not contain `access_token` or `refresh_token`
