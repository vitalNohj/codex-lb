# api-keys (delta)

## ADDED Requirements

### Requirement: Shared API keys see only themselves

The system SHALL store an `is_shared` boolean on every API key, defaulting to `false`. `POST /api/api-keys` and `PATCH /api/api-keys/{id}` SHALL accept `isShared`, and every `ApiKeyResponse` SHALL include it. Changing `isShared` MUST NOT change the key's stored `usage_sections`.

A shared key SHALL see only its own usage, limits and expiry, whatever its `usage_sections` and the global privacy setting say. The decision MUST be made by one check in `app/modules/api_keys/visibility.py`. For a shared key:

- `GET /v1/usage` SHALL return the key's own usage, own `limits[]` and `expires_at`, with `upstream_limits` empty, `account_pool_usage` null, and no upstream windows mirrored into `limits[]`.
- `GET /api/codex/usage` SHALL return only the key's own limits.
- `GET` and `POST /v1/reset-credit`, `GET /v1/quota-feed`, `GET /api/oauth/usage`, `POST /v1/warmup` and `POST /v1/warmup/{mode}` SHALL answer `403` with error code `shared_api_key_not_allowed`, before any upstream work.
- `GET /api/fleet/summary`, `GET /api/fleet/observability` and `POST /api/fleet/refresh` SHALL answer `403` with error code `permission_denied`, before any refresh work.
- Proxied responses SHALL NOT carry the pool-wide `x-codex-primary-*`, `x-codex-secondary-*`, `x-codex-monthly-*` or `x-codex-credits-*` headers.

An unshared key SHALL keep the behavior its `usage_sections` and the global privacy setting give it.

#### Scenario: New and existing keys are unshared

- **WHEN** admin creates a key without `isShared`, or the database is upgraded with existing keys
- **THEN** those keys return `isShared: false` and keep their `usageSections`

#### Scenario: Toggle round-trip keeps usage sections

- **GIVEN** a key with `usageSections: "upstream_limits,account_pool_usage,reset_credits"`
- **WHEN** admin sets `isShared` to `true` and then back to `false`
- **THEN** the key returns the same `usageSections` both times
- **AND** after the second change it can use `/v1/reset-credit` again

#### Scenario: Shared key with every section sees nothing of the pool

- **GIVEN** a shared key whose `usageSections` include every section
- **WHEN** it calls `/v1/usage`, `/v1/reset-credit`, `/v1/quota-feed`, `/api/fleet/*`, `/api/oauth/usage` or `/v1/warmup`, or sends a proxied request
- **THEN** no response contains an account email, account id, reset credit, pool or upstream quota, or `x-codex-*` quota header

#### Scenario: Shared key sees its own budget

- **GIVEN** a shared key with a daily `cost_usd` limit and an expiry
- **WHEN** it calls `GET /v1/usage`
- **THEN** `limits[]` contains that limit with its remaining value and `expires_at` is set

#### Scenario: Unshared key keeps its capabilities

- **GIVEN** an unshared key with every section
- **THEN** it can list and redeem reset credits, read fleet summary with emails, observability and refresh, read Codex rows in the quota feed, read pooled OAuth usage, run warmup and receive quota headers

### Requirement: `/api/codex/usage` lists the key's other limits

For an API-key caller, `GET /api/codex/usage` SHALL report each of the key's own limits that the credit windows do not show (cost, token and model-scoped limits) as an entry of `additional_rate_limits` with `limit_name` `api_key:{limit_type}:{limit_window}[:{model_filter}]`, `metered_feature` `api_key_{limit_type}` and a single primary window carrying the used percentage, window length and reset time.

#### Scenario: Cost cap visible in Codex status

- **GIVEN** a key with a daily `cost_usd` limit at 25% use
- **WHEN** it calls `GET /api/codex/usage`
- **THEN** `additional_rate_limits` contains `api_key:cost_usd:daily` with `primary_window.used_percent` 25 and `limit_window_seconds` 86400

### Requirement: Dashboard shared-key toggle

The API key create and edit dialogs SHALL show a "Shared key" checkbox with a help tooltip explaining it is for a key given to a friend or client. While it is checked, the usage-sections picker SHALL be disabled with a note that the sections are overridden; its value SHALL be kept and submitted unchanged. Shared keys SHALL carry a "Shared" badge in the API key lists. The strings SHALL exist in en, ko and zh-CN.

#### Scenario: Picker overridden while shared

- **WHEN** admin checks "Shared key" in the edit dialog
- **THEN** the usage-sections picker is disabled and described as overridden
- **AND** saving submits `isShared: true` with the key's existing `usageSections`
