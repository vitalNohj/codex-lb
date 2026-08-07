## ADDED Requirements

### Requirement: Claude sidecar reauth mapping requires auth-death evidence
Dashboard Claude per-auth status MUST map to `reauth_required` only when CLIProxyAPI auth-file evidence indicates credential/session death, not when the auth is merely unavailable with a generic error. Auth-death evidence MUST be either (1) a `status_message` containing `authentication_error`, `re-authenticate`, `invalid_grant`, or both `oauth` and `expired` (case-insensitive), or (2) `unavailable=true` with `status=unauthorized`. An auth with `unavailable=true` and `status=error` (including transient messages such as `context canceled`) MUST NOT be mapped to `reauth_required`; the dashboard MUST preserve the raw status for that auth. Badge chrome and copy MUST remain unchanged.

#### Scenario: Transient context canceled stays non-reauth
- **WHEN** a Claude auth snapshot row has `unavailable=true`, `status="error"`, and `status_message="context canceled"`
- **THEN** the accounts summary `sidecar_auths` entry status is not `reauth_required`

#### Scenario: Explicit authentication_error still maps to reauth
- **WHEN** a Claude auth snapshot row has `unavailable=true` and a `status_message` containing `authentication_error` and `Re-authenticate`
- **THEN** the accounts summary `sidecar_auths` entry status is `reauth_required`

#### Scenario: Unauthorized without message still maps to reauth
- **WHEN** a Claude auth snapshot row has `unavailable=true`, `status="unauthorized"`, and an empty `status_message`
- **THEN** the accounts summary `sidecar_auths` entry status is `reauth_required`
