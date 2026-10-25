## MODIFIED Requirements

### Requirement: Break-glass sign-in is audited at critical severity

A sign-in of an account carrying the break-glass designation **that completes a second factor while `local_login_policy` is restricted** (`admins_only` or `break_glass_only`, read when the second factor is verified) SHALL emit one audit row `break_glass_login` with `severity` `critical`, the account as actor and target, the authentication method, and the client address, in addition to the ordinary `login_success` row. While the policy is `enabled`, password sign-in is open to every account, so the designated account's sign-in is the ordinary way in: it SHALL write the ordinary `login_success` row and SHALL NOT write `break_glass_login`. The always-two-factor rule does not depend on the policy and is unchanged. The session it mints SHALL carry the emergency marker so the dashboard can say so while the policy is restricted (see **Session response describes the account and the login screen**). A designated account holding no secret presents no factor, so its sign-in SHALL NOT write the row — otherwise every upgraded install would record a critical event on each ordinary sign-in of its `admin` account, and the severity would stop meaning anything. That account SHALL still be able to sign in and reach the enrolment routes while the policy is `enabled`, so the migrated install can never lock itself out of qualifying; the state it signs in under is specified in **A designation without a second factor signs in as an ordinary admin** below.

#### Scenario: The emergency sign-in is recorded

- **GIVEN** `local_login_policy` is `admins_only` or `break_glass_only`
- **WHEN** a break-glass admin completes password and TOTP
- **THEN** an audit row `break_glass_login` exists with severity `critical` naming that account
- **AND** an ordinary admin signing in writes no such row

#### Scenario: The designated admin's sign-in is ordinary while the policy is open

- **GIVEN** `local_login_policy` is `enabled`
- **WHEN** a break-glass admin that holds a TOTP secret completes password and TOTP
- **THEN** it was still asked for the second factor, and the `login_success` row is written
- **AND** no `break_glass_login` row exists and the session response reports `break_glass_session: false`

#### Scenario: The migrated admin can still get in and enrol

- **GIVEN** `local_login_policy` is `enabled` and the designated `admin` account has no TOTP secret
- **WHEN** it signs in with its password
- **THEN** the session is issued and the enrolment routes serve it

### Requirement: A designation without a second factor signs in as an ordinary admin

The always-two-factor rule binds an account that **holds** a secret, so a designated account with `totp_secret_encrypted` null SHALL meet the install's own TOTP policy and nothing more — it SHALL NOT be asked for a factor it does not hold, and it SHALL NOT be refused for lacking one. Under `enabled` and `admins_only` its password step SHALL therefore succeed exactly as it would for any other admin of that install: with both `totp_required_on_login` and `totp_required_for_admin_role` off the session is fully authenticated, and when either applies the session SHALL be issued in the `totp_enrollment_required` state already specified for accounts without a secret (`authenticated: true`, `totp_enrollment_required: true`, `/totp/setup/start` and `/totp/setup/confirm` served, every other dashboard route `403 totp_enrollment_required`). That is the path an upgraded install walks to reach its first qualifying account, so neither state may be closed off. Under `break_glass_only` the same account SHALL be refused `401 invalid_credentials` like any other account the policy does not admit, because the strictest policy admits qualification and not designation. Under `admins_only` the session SHALL still report `break_glass_session: true` (the indicator names the designation under a restricted policy, which is the rule the session response states), and under `enabled` it SHALL report `false`. In both cases the critical `break_glass_login` row belongs to the second factor and SHALL NOT be written. Once the account confirms a secret the enrolled rule takes over from the next request: the enrolment itself mints no TOTP-verified session, so the session it enrolled from SHALL be refused `401 totp_required` until `/totp/verify` completes it.

#### Scenario: An install that requires two-factor sends the designation to enrolment

- **GIVEN** `totp_required_on_login` is on and the designated `admin` account holds a password and no TOTP secret
- **WHEN** it submits its correct password
- **THEN** the response is `200` with `authenticated: true`, `totp_enrollment_required: true`, and `break_glass_session` true under `admins_only` and false under `enabled`
- **AND** `/api/settings` answers `403 totp_enrollment_required` while `/totp/setup/start` and `/totp/setup/confirm` serve it
- **AND** no `break_glass_login` row exists, because no second factor was presented

#### Scenario: Enrolment hands the account to the enrolled rule

- **GIVEN** that account has just confirmed its first TOTP secret on the session it enrolled from
- **WHEN** it requests `/api/settings`
- **THEN** the response is `401 totp_required`
- **AND** `/totp/verify` with a valid code serves the next request and, under `admins_only`, writes one critical `break_glass_login` row (none under `enabled`)

### Requirement: Session cookies bind to an account and are re-validated on every request

Account session cookies SHALL carry payload version `2` with the account id (`uid`), the account's `session_generation` at issue time (`sg`), issued-at and expiry times, whether the password (`pv`) and TOTP (`tp`) steps were completed, the authentication method (`am`), and optionally the unix time of the account's last step-up re-verification (`su`). Guest cookies SHALL carry version `2`, a `guest` marker, and the guest session generation (`gg`). Cookies whose payload lacks version `2`, carries the previous keys (`pw`, `tv`, `role`, `gv`), or is malformed MUST be rejected. On every request the system MUST load the account named by `uid` and refuse the session with `401 authentication_required` when the account does not exist, is not `active`, or its `session_generation` differs from `sg`. The principal built for a valid account session MUST carry the account id, username, role slug, authentication method, the grants resolved from the account's role, and `su` as `step_up_verified_at`; its wire `role` MUST remain `admin`. A session minted for an account carrying the break-glass designation SHALL additionally set the emergency marker (`bg`) on the same version-2 payload; the marker is optional and its absence means false, so cookies minted before this release keep decoding and the payload version does not change. The principal built from such a cookie MUST carry the marker.

#### Scenario: Previous-release cookie is refused

- **WHEN** a request presents a cookie whose payload uses the `pw`/`tv`/`role` keys
- **THEN** the session is treated as absent and protected routes answer `401 authentication_required`

#### Scenario: Disabled account loses its sessions

- **GIVEN** an account with an outstanding session cookie
- **WHEN** the account's `status` becomes `disabled`
- **THEN** requests carrying that cookie answer `401 authentication_required`

#### Scenario: Generation bump revokes cookies

- **GIVEN** an account with an outstanding session cookie
- **WHEN** the account's `session_generation` is incremented
- **THEN** requests carrying that cookie answer `401 authentication_required`
- **AND** a cookie issued after the bump is accepted

#### Scenario: Cookie without a step-up

- **WHEN** a version-2 cookie carries no `su`
- **THEN** the session is accepted and its principal's `step_up_verified_at` is absent

#### Scenario: Emergency session is marked

- **GIVEN** a break-glass admin completes its password and TOTP steps
- **WHEN** the session cookie is decoded
- **THEN** it carries the emergency marker under every `local_login_policy`, and the session response reports the emergency session while the policy is restricted
- **AND** a session minted for any other account carries no marker

#### Scenario: Cookie minted before this release still decodes

- **WHEN** a version-2 cookie without the emergency marker is presented
- **THEN** the session is accepted and reports no emergency session

### Requirement: Session response describes the account and the login screen

`GET /api/dashboard-auth/session` (and the session-issuing endpoints) SHALL add the optional fields `user` (`{id, username, display_name, role: {id, slug, name, kind}}` or null), `auth_method`, `must_change_password`, `totp_enrollment_required`, `login`, `access_summary`, `assignable_role_ids`, and `step_up`. `login` MUST be present for every caller, MUST never contain a username, MUST set `username_field` to `hidden` exactly when one active account holds a password and to `shown` otherwise, MUST list the active providers in `providers` (`{kind, provider_key, label, login_url}`; `password` first, `trusted_header` when active, `oidc` when active; `login_url` is the provider's own sign-in start path for a redirect-style provider and null for the others), MUST set `pending_identity` to true exactly when the request carried a provider identity that resolved to no active account **or** carries the sealed refusal marker an OIDC callback left for this browser, MUST carry `pending_arrival` (`{provider, reference}`) exactly when that marker is present and readable — `provider` being the label of the row the marker names and `reference` the masked address it carries — and `null` otherwise, so a reverse-proxy refusal keeps the bare boolean it has today, and MUST report `local_login` as the effective `local_login_policy` (`enabled`, `admins_only` or `break_glass_only`) so the login screen knows whether the local password form is shown, collapsed behind a link, or reachable only at `/login?local=1`. `login` MUST NOT name the break-glass account or any other username to an unauthenticated caller; the account name is served only to the authenticated `security:write` caller who can act on it. `pending_arrival` MUST be derived from that marker and from nothing else — not from the active providers, not from any account lookup — so no caller can obtain the block for an address of their choosing, and what it returns is a lossy projection of an identity this browser itself presented, never a statement that an account exists. `access_summary` (`users_total`, `users_active`, `users_invited`, `users_disabled`, `pending_invites`, `non_admin_users`, `custom_roles`, `providers_enabled` = the active provider kinds, `role_mappings`, `scim_tokens`, `audit_sinks`, `local_login_policy`) and a non-empty `assignable_role_ids` MUST be returned only to an authenticated principal holding `users:manage`; every other caller MUST receive `null` and `[]`. `assignable_role_ids` MUST list exactly the `admin`, `operator`, and `viewer` presets in this release (`member` becomes assignable when own-scoped views ship; `guest` never). `step_up` (`{verified_at, expires_at, methods}`) MUST be returned for signed-in accounts only: `verified_at`/`expires_at` are set when a step-up recorded for the account is still within 300 seconds (from the session cookie's `su` or the step-up cookie) and null otherwise, and `methods` lists the factors the account must present (`password`, `totp`, both, `oidc`, or none); every other caller MUST receive `null`. `break_glass_session` MUST be true exactly when the session was minted for an account carrying the break-glass designation **and** the current `local_login_policy` is restricted (`admins_only` or `break_glass_only`), and false otherwise (never null for a signed-in account), so the header can show the emergency-session indicator. The policy MUST be read for each session response, not taken from the cookie, so loosening the policy drops the indicator from sessions that already exist and tightening it adds the indicator. `permissions` MUST keep the `read`/`write` aliases and additionally list every grant as `<permission>:<scope>`. `role` MUST remain `admin` or `guest`. `password_required` MUST equal the derived "sign-in required" state, except that a header-less request in `trusted_header` mode while no active account holds a password reports `password_required=false` and `authenticated=false` (the client shows the reverse-proxy notice, not a login form). A trusted-header request resolved to an account SHALL be described like that account's session (`authenticated=true`, `user`, `auth_method=trusted_header`, the account's permissions, team facts when it holds `users:manage`); `password_session_active` reports whether a fallback password cookie the login policy admits also rode along, which an OIDC session is not.

#### Scenario: Signed-in admin sees the account block and the summary

- **WHEN** an admin account requests the session
- **THEN** `user.username` is the account's username, `auth_method` is `password`, `login.username_field` is `hidden`
- **AND** `access_summary.users_total` counts every account and `permissions` contains `read`, `write`, and `users:manage:all`

#### Scenario: Guest and unauthenticated callers get no team facts

- **WHEN** a guest session or an unauthenticated client requests the session
- **THEN** `access_summary` is null, `assignable_role_ids` is empty, `user` is null and `step_up` is null
- **AND** `login` is present without any username

#### Scenario: Refused proxy identity

- **WHEN** a trusted-header request whose identity resolves to no active account asks for the session
- **THEN** `authenticated` is false, `user` is null and `login.pending_identity` is true

#### Scenario: Step-up block follows the account

- **GIVEN** a password account without TOTP that signed in 301 seconds ago and has not stepped up since
- **WHEN** it requests the session
- **THEN** `step_up` is `{verified_at: null, expires_at: null, methods: ["password"]}`
- **AND** after a successful `/step-up` the block carries `verified_at` and `expires_at = verified_at + 300`

#### Scenario: Unauthenticated caller learns the policy but no name

- **GIVEN** `local_login_policy` is `break_glass_only`
- **WHEN** an unauthenticated client requests the session
- **THEN** `login.local_login` is `break_glass_only` and `login.providers` lists the active providers
- **AND** the response contains no username and `access_summary` is null

#### Scenario: Emergency session is reported

- **GIVEN** `local_login_policy` is `admins_only` or `break_glass_only`
- **WHEN** a break-glass admin that completed both factors requests the session
- **THEN** `break_glass_session` is true
- **AND** the same field is false for every other signed-in account

#### Scenario: The emergency label follows the policy in force

- **GIVEN** a break-glass admin signed in while the policy was `break_glass_only`
- **WHEN** the policy is changed to `enabled` and the same session requests the session again
- **THEN** `break_glass_session` is false
- **AND** after the policy is changed to `admins_only`, the same session reports `true` again and no audit row is written by either change of label

#### Scenario: A refused company sign-in describes itself to the browser that was refused

- **GIVEN** a browser carrying the sealed refusal marker an OIDC callback left for it
- **WHEN** it requests the session
- **THEN** `authenticated` is false, `user` is null, `login.pending_identity` is true and `login.pending_arrival` carries the provider row's label with the masked address
- **AND** the same request without that cookie reports `pending_identity` false and `pending_arrival` null, and neither answer says whether any account exists

#### Scenario: An active OIDC provider is advertised with its start path

- **GIVEN** an enabled and active OIDC row labelled by the operator
- **WHEN** any caller requests the session
- **THEN** `login.providers` contains an entry of kind `oidc` carrying that label and a `login_url` of the OIDC sign-in start path
- **AND** the entry disappears when the row is disabled, and the client that does not know the kind ignores it
