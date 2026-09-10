# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Claude OAuth credentials with auth-failure evidence are reauth_required

Codex-lb MUST set each Claude sidecar auth row's `status` to `reauth_required` when CLIProxyAPI reports explicit auth-failure evidence: a `status_message` equal to `unauthorized`, or containing `invalid_grant`, `authentication_error`, `re-authenticate`, `refresh token expired`, or an expired OAuth/access-token message; or `unavailable` together with `status=unauthorized`. The `unauthorized` message MUST be matched exactly after trimming and case folding, never as a substring, because CLIProxyAPI's generic failure branch can leave raw upstream error text that merely contains the word.

Codex-lb MUST NOT derive `reauth_required` from the OAuth access-token expiry at any lapse duration. CLIProxyAPI renews Claude access tokens from a background refresh loop and exposes no field distinguishing a dead refresh token from a pending refresh, a not-yet-flushed write, a restarted sidecar or clock skew, so expiry age is suggestive rather than evidence.

Codex-lb MUST NOT badge a quota-exceeded or operator-paused credential as `reauth_required`, regardless of its expiry.

#### Scenario: Lapsed access-token expiry alone does not show Re-auth required

- **GIVEN** a Claude auth whose `expired` timestamp lapsed, by minutes or by months
- **AND** CLIProxyAPI still lists that file as `status=active` and `unavailable=false`
- **AND** no auth-death status message is present
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is unchanged and is not `reauth_required`

#### Scenario: Unexpired access token does not show Re-auth required

- **GIVEN** a Claude auth file whose `expired` timestamp is in the future
- **AND** no auth-death status message is present
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is not `reauth_required`

#### Scenario: A transient message containing "unauthorized" is not re-auth

- **GIVEN** a Claude auth whose `status_message` is a transient upstream error that contains the word `unauthorized`
- **AND** that message is not exactly `unauthorized`
- **WHEN** the accounts list or Claude sidecar quota snapshot is built
- **THEN** that sidecar auth row's `status` is unchanged and is not `reauth_required`

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
