# fleet-summary (delta)

## MODIFIED Requirements

### Requirement: Fleet summary requires API key authentication

The system SHALL expose `GET /api/fleet/summary` for trusted local fleet
consumers. The route MUST require a valid Bearer API key even when global proxy
API-key authentication is disabled. The account list is the key's Codex
account pool: a key without `account_pool_usage`, or any key while
`hide_upstream_quota_from_api_keys` is enabled, MUST receive an empty
`accounts` list. Account identity (`email` and `displayName`) MUST be `null`
unless the key can view per-account usage. For callers allowed to view upstream
usage, each account SHALL expose `lastRefreshAt` as OAuth token freshness and
`usageRefreshedAt` as quota-snapshot freshness. `usageRefreshedAt` MUST equal
the newest `recorded_at` value among the persisted usage samples used to build
that account summary, or `null` when no such sample exists.

#### Scenario: Missing fleet summary key is rejected

- **WHEN** a client calls `GET /api/fleet/summary` without a Bearer token
- **THEN** the system returns 401
- **AND** no account summary payload is returned

#### Scenario: Valid fleet summary key returns account capacity

- **WHEN** a client calls `GET /api/fleet/summary` with a valid Bearer API key
  whose `usage_sections` include `upstream_limits` and `account_pool_usage`
- **THEN** the response includes `accounts[]`
- **AND** each account includes `accountId`, `displayName`, `email`, `status`,
  `planType`, `primary`, `secondary`, `lastRefreshAt`, and `usageRefreshedAt`
- **AND** each window includes `remainingPercent`, `resetAt`, and `windowMinutes`

#### Scenario: Usage refresh advances independently of OAuth refresh

- **GIVEN** an account has an existing quota snapshot and OAuth refresh time
- **WHEN** force probe or fleet refresh persists a newer usage sample without
  refreshing OAuth credentials
- **THEN** `usageRefreshedAt` advances to the newer usage sample time
- **AND** `lastRefreshAt` remains unchanged

#### Scenario: Usage freshness is unavailable

- **WHEN** an account has no persisted usage sample
- **THEN** `usageRefreshedAt` is `null`

#### Scenario: Usage visibility is denied

- **WHEN** the authenticated key cannot view upstream usage
- **THEN** `usageRefreshedAt` is `null`
- **AND** `lastRefreshAt` is `null`

#### Scenario: Key without account_pool_usage sees no accounts

- **WHEN** a valid API key without `account_pool_usage` calls `GET /api/fleet/summary`
- **OR** the global API-key quota privacy setting hides upstream quota data
- **THEN** the system returns 200 with `accounts: []`
- **AND** no account id or email appears in the response

#### Scenario: Key without per-account usage sees no account identity

- **WHEN** a valid API key with `account_pool_usage` but without `upstream_limits` calls `GET /api/fleet/summary`
- **THEN** each account has `email: null` and `displayName: null`
- **AND** usage windows and refresh times are `null`

### Requirement: Fleet refresh requests existing usage refresh policy

The system SHALL expose `POST /api/fleet/refresh` for trusted local fleet consumers. The route MUST require a valid Bearer API key even when global proxy API-key authentication is disabled. The route MUST answer `403` with the dashboard error code `permission_denied`, before creating any refresh work, unless the key can view fleet usage (its `usage_sections` include `upstream_limits` and `account_pool_usage`, and the global API-key quota privacy setting is off). The route MUST request a usage refresh through codex-lb's existing usage refresh machinery and MUST NOT refresh inside proxy account selection.

The route MUST preserve existing usage-refresh rules for disabled refresh, fresh samples, auth cooldowns, paused accounts, reauth-required accounts, and deactivated accounts.

#### Scenario: Fleet refresh returns minimal outcome

- **WHEN** a valid client that can view fleet usage calls `POST /api/fleet/refresh`
- **THEN** the response includes `ok: true`, `usageWritten`, `accountCount`, `attemptedCount`, and `generatedAt`
- **AND** the response does not include account credentials or token material

#### Scenario: Fleet refresh skips unsafe account states

- **GIVEN** active and paused accounts exist
- **WHEN** a valid client calls `POST /api/fleet/refresh`
- **THEN** active accounts are eligible for the refresh attempt
- **AND** paused, reauth-required, and deactivated accounts are not attempted

#### Scenario: Key that cannot view fleet usage cannot refresh

- **WHEN** a valid API key without both `upstream_limits` and `account_pool_usage` calls `POST /api/fleet/refresh`
- **OR** the global API-key quota privacy setting is on
- **THEN** the system returns 403 with code `permission_denied`
- **AND** no usage refresh is started
