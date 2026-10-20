# api-keys (delta)

## MODIFIED Requirements

### Requirement: API key usage_sections controls visible /v1/usage detail sections

The system SHALL accept an optional `usage_sections` field in `POST /api/api-keys` and `PATCH /api/api-keys/{id}`. The field SHALL be a comma-separated string of section names. Supported values SHALL be `upstream_limits`, `account_pool_usage` and `reset_credits`. When `usage_sections` is omitted during creation, the system SHALL default it to `"upstream_limits,account_pool_usage"`; a new key MUST NOT get `reset_credits` unless the admin selects it.

`upstream_limits` grants pool-wide upstream quota (aggregate Codex credit windows and CLIProxyAPI credential quota). `account_pool_usage` grants the key's Codex account pool (account list and pooled remaining capacity). Per-account Codex usage and account identity (email, display name) MUST require both sections. When `hide_upstream_quota_from_api_keys` is enabled, an API key MUST be treated as having neither `upstream_limits` nor `account_pool_usage`, whatever its `usage_sections` say. `reset_credits` grants self-service reset-credit access and is not affected by that setting.

The `ApiKeyResponse` SHALL include `usage_sections` as a string.

#### Scenario: Create key with explicit usage_sections

- **WHEN** admin submits `POST /api/api-keys` with `{ "name": "dev-key", "usageSections": "upstream_limits" }`
- **THEN** the created key returns `usageSections: "upstream_limits"`

#### Scenario: Create key without usage_sections defaults to all

- **WHEN** admin submits `POST /api/api-keys` without `usageSections`
- **THEN** the created key returns `usageSections: "upstream_limits,account_pool_usage"`

#### Scenario: Create key without usage_sections excludes reset credits

- **WHEN** admin submits `POST /api/api-keys` without `usageSections`
- **THEN** the created key's `usageSections` do not include `reset_credits`
- **AND** the key cannot use `/v1/reset-credit`

#### Scenario: Admin enables reset credits on a key

- **WHEN** admin submits `PATCH /api/api-keys/{id}` with `{ "usageSections": "upstream_limits,reset_credits" }`
- **THEN** the key returns `usageSections: "upstream_limits,reset_credits"`
- **AND** the key can list and redeem reset credits of its account pool

#### Scenario: Update key usage_sections

- **WHEN** admin submits `PATCH /api/api-keys/{id}` with `{ "usageSections": "account_pool_usage" }`
- **THEN** the key returns `usageSections: "account_pool_usage"`

#### Scenario: Reject unknown usage_sections values

- **WHEN** admin submits `POST /api/api-keys` with `usageSections` containing an unsupported value
- **THEN** the system returns 400

#### Scenario: Existing keys after the upgrade

- **GIVEN** API keys created before `reset_credits` existed
- **WHEN** the database is upgraded with the shipped migration choice
- **THEN** their `usage_sections` are unchanged and they do not have `reset_credits`
- **AND** an admin can enable `reset_credits` per key in the dashboard create and edit dialogs

### Requirement: API keys can read their own `/v1/usage`

The system SHALL expose `GET /v1/usage` for self-service usage lookup by API-key clients. The route MUST require a valid API key in the `Authorization` header using the Bearer authentication scheme even when `api_key_auth_enabled` is false globally. The response MUST include only data for the authenticated key and explicitly visible aggregate upstream quota sections, and MUST return:

- `request_count`
- `total_tokens`
- `cached_input_tokens`
- `total_cost_usd`
- `limits[]` containing limits configured on the authenticated API key, with `limit_type`, `limit_window`, `max_value`, `current_value`, `remaining_value`, `model_filter`, `reset_at`, and `source`. When no API-key limits are configured and aggregate upstream quota details are visible to the caller, `limits[]` MAY mirror those aggregate upstream credit windows for legacy client compatibility. When they are not visible (the key lacks `upstream_limits`, or the quota privacy setting is on), `limits[]` MUST NOT contain them.
- `upstream_limits[]` containing aggregate upstream Codex credit windows when available, with the same fields and `source: "aggregate"`, subject to the key's `usage_sections` containing `upstream_limits`
- `account_pool_usage` containing `primary` and `secondary` float remaining percentages, subject to the key's `usage_sections` containing `account_pool_usage`
- `expires_at`, the key's expiry as an ISO 8601 UTC timestamp ending in `Z`, or `null` when the key does not expire

Validation failures MUST use the existing OpenAI error envelope used by `/v1/*` routes.

#### Scenario: Missing API key is rejected

- **WHEN** a client calls `GET /v1/usage` without a Bearer token
- **THEN** the system returns 401 in the OpenAI error format

#### Scenario: Invalid API key is rejected

- **WHEN** a client calls `GET /v1/usage` with an unknown, expired, or inactive Bearer key
- **THEN** the system returns 401 in the OpenAI error format

#### Scenario: Key with no usage returns zero totals

- **WHEN** a valid API key with no request-log usage calls `GET /v1/usage`
- **THEN** the system returns `request_count: 0`, `total_tokens: 0`, `cached_input_tokens: 0`, `total_cost_usd: 0.0`

#### Scenario: Usage is scoped to the authenticated key

- **WHEN** multiple API keys have request-log history and one of them calls `GET /v1/usage`
- **THEN** the response includes only the usage totals and limits for that authenticated key

#### Scenario: Upstream limits are separate from API-key limits

- **WHEN** an API key with its own limit calls `GET /v1/usage`
- **AND** upstream Codex aggregate usage data exists
- **THEN** `limits[]` contains the API-key limit values
- **AND** `upstream_limits[]` contains the aggregate Codex credit windows

#### Scenario: Upstream limits are mirrored for legacy clients without API-key limits

- **WHEN** an API key without its own limits calls `GET /v1/usage`
- **AND** upstream Codex aggregate usage data is visible to the key
- **THEN** `upstream_limits[]` contains the aggregate Codex credit windows
- **AND** `limits[]` contains the same aggregate Codex credit windows for legacy client compatibility

#### Scenario: Self-usage works while global proxy auth is disabled

- **WHEN** `api_key_auth_enabled` is false and a client calls `GET /v1/usage` with a valid Bearer key
- **THEN** the system still authenticates that key and returns the self-usage payload

#### Scenario: Key without sections sees only its own usage

- **GIVEN** an unscoped API key with empty `usage_sections` and no limits of its own
- **AND** upstream Codex aggregate usage data exists
- **WHEN** the client calls `GET /v1/usage`
- **THEN** `limits[]` and `upstream_limits[]` are empty and `account_pool_usage` is `null`

#### Scenario: Key expiry is returned

- **GIVEN** an API key that expires at `2031-03-04T05:06:07Z`
- **WHEN** the client calls `GET /v1/usage`
- **THEN** the response includes `expires_at: "2031-03-04T05:06:07Z"`

### Requirement: API-key quota privacy toggle
The system SHALL provide a `hide_upstream_quota_from_api_keys` boolean in `DashboardSettings`, defaulting to `false`. The dashboard settings API SHALL accept and return this field.

#### Scenario: Default preserves current behavior

- **WHEN** the setting is not enabled
- **THEN** API-key-authenticated requests continue to receive upstream quota details exactly as they do today

#### Scenario: API-key usage response hides upstream limits

- **GIVEN** `hide_upstream_quota_from_api_keys` is `true`
- **WHEN** an API-key-authenticated client calls `GET /v1/usage`
- **THEN** the response SHALL omit upstream quota entries
- **AND** the response SHALL still include the API key's own quota data

#### Scenario: API-key usage response hides account pool usage

- **GIVEN** `hide_upstream_quota_from_api_keys` is `true`
- **AND** the API key's `usage_sections` includes `account_pool_usage`
- **WHEN** an API-key-authenticated client calls `GET /v1/usage`
- **THEN** the response SHALL set `account_pool_usage` to `null`
- **AND** the privacy toggle SHALL take precedence over the API key's `usage_sections`

#### Scenario: Proxy responses hide upstream quota headers

- **GIVEN** `hide_upstream_quota_from_api_keys` is `true`
- **WHEN** an API-key-authenticated client calls a protected proxy route that emits quota headers, including Responses requests served by OpenCode Go, OmniRoute, or another chat-provider sidecar
- **THEN** the response SHALL NOT include `x-codex-primary-*`, `x-codex-secondary-*`, or `x-codex-credits-*` headers
- **AND** internal routing headers such as `x-codex-turn-state` SHALL remain unchanged

#### Scenario: Dashboard views stay visible

- **GIVEN** `hide_upstream_quota_from_api_keys` is `true`
- **WHEN** an owner views dashboard settings or owner-facing usage data without API-key authentication
- **THEN** upstream quota details SHALL remain visible

### Requirement: API keys can inspect and redeem reset credits within their account pool

The system SHALL expose `GET /v1/reset-credit` and `POST /v1/reset-credit` for API-key-authenticated self-service reset-credit access. Both routes MUST require a valid `Authorization: Bearer sk-clb-...` header even when `api_key_auth_enabled` is false globally. Validation failures MUST use the existing OpenAI error envelope used by `/v1/*` routes.

Both routes MUST answer `403` in the OpenAI error envelope, before reading accounts, refreshing credentials, or calling upstream, unless the authenticated key's `usage_sections` include `reset_credits`.

The target account pool SHALL be derived from the authenticated API key. If `account_assignment_scope_enabled=true`, only `assigned_account_ids` SHALL be eligible. If account scope is not enabled, all selectable accounts SHALL be eligible.

`GET /v1/reset-credit` SHALL return only credits for the authenticated key's eligible account pool. `POST /v1/reset-credit` SHALL reject requests whose `account_id` is outside that pool.

Before `POST /v1/reset-credit` decrypts and forwards the bearer token for the upstream consume call, the system SHALL refresh the target account with the normal account-token freshness rules and use the refreshed account credentials for the consume request.

If that self-service credential refresh fails, `POST /v1/reset-credit` SHALL stop before the upstream consume call, return a client-actionable conflict response, and keep using the existing `/v1/*` OpenAI error envelope.

After acquiring the cross-replica redeem claim, `POST /v1/reset-credit` SHALL re-validate the requested `redeem_id` against a live upstream reset-credits fetch performed inside the serialized redeem section using the refreshed account credentials, regardless of whether the replica-local snapshot lists the credit as available. It MUST NOT consume a credit solely on the basis of the replica-local snapshot, because a peer replica may have redeemed that credit while this request waited for the claim and the local snapshot can remain stale until its invalidation poll fires. The upstream fetch response is authoritative: if the credit is available upstream the redemption proceeds; otherwise the endpoint returns 409 and replaces the cached snapshot for that account with the fresh upstream snapshot.

On a successful `POST /v1/reset-credit` redemption, the system SHALL invalidate the redeemed account's cached reset-credit snapshot, force a usage refresh for that account, and invalidate account-selection cache state when that usage refresh writes updated usage. A failed or empty post-redeem usage refresh SHALL NOT roll back the successful credit redemption response.

#### Scenario: Missing API key is rejected

- **WHEN** a client calls `GET /v1/reset-credit` or `POST /v1/reset-credit` without a Bearer token
- **THEN** the system returns 401 in the OpenAI error format

#### Scenario: Invalid API key is rejected

- **WHEN** a client calls `GET /v1/reset-credit` or `POST /v1/reset-credit` with an unknown, expired, or inactive Bearer key
- **THEN** the system returns 401 in the OpenAI error format

#### Scenario: Key without the reset_credits section is refused

- **GIVEN** a valid API key whose `usage_sections` do not include `reset_credits`
- **WHEN** the client calls `GET /v1/reset-credit` or `POST /v1/reset-credit`
- **THEN** the system returns 403 in the OpenAI error format
- **AND** the response contains no account id or email
- **AND** no credit is redeemed and no upstream call is made

#### Scenario: Scoped API key sees only assigned accounts

- **WHEN** an API key with the `reset_credits` section has account scope enabled with assigned accounts
- **AND** the client calls `GET /v1/reset-credit`
- **THEN** the response includes reset-credit entries only for those assigned accounts

#### Scenario: Unscoped API key can read the full selectable pool

- **WHEN** an API key with the `reset_credits` section has account scope disabled
- **AND** the client calls `GET /v1/reset-credit`
- **THEN** the response may include reset-credit entries for any selectable account that currently has an available cached credit

#### Scenario: Out-of-pool account is rejected on redeem

- **WHEN** a client calls `POST /v1/reset-credit` with an `account_id` outside the authenticated API key's eligible pool
- **THEN** the system returns 403 without redeeming any credit

#### Scenario: Self-service reset-credit works while global proxy auth is disabled

- **WHEN** `api_key_auth_enabled` is false and a client calls `GET /v1/reset-credit` or `POST /v1/reset-credit` with a valid Bearer key
- **THEN** the system still authenticates that key and applies the same account-pool rules

#### Scenario: Self-service redemption refreshes stale account credentials before consume

- **GIVEN** an eligible account has a redeemable reset credit
- **AND** the persisted access token for that account is stale but refreshable
- **WHEN** a client successfully calls `POST /v1/reset-credit` for that account
- **THEN** codex-lb refreshes the account before decrypting the consume bearer token
- **AND** the upstream reset-credit consume call uses the refreshed account credentials

#### Scenario: Self-service redemption surfaces refresh failures as conflicts

- **GIVEN** an eligible account has a redeemable reset credit
- **AND** that account's credential refresh fails before the upstream consume call
- **WHEN** a client calls `POST /v1/reset-credit` for that account
- **THEN** codex-lb returns a conflict response in the standard `/v1/*` OpenAI error envelope
- **AND** codex-lb does not call upstream reset-credit consume for that request

#### Scenario: Fresh replica redeems a credit missing from its local snapshot

- **GIVEN** a freshly started replica whose reset-credit snapshot store is empty for the target account
- **AND** upstream reports the requested `redeem_id` as available
- **WHEN** a client calls `POST /v1/reset-credit` for that account and `redeem_id`
- **THEN** the replica fetches the account's reset credits from upstream inside the serialized redeem section
- **AND** the redemption proceeds and succeeds instead of returning a false 409

#### Scenario: Credit already redeemed elsewhere returns 409 with a fresh snapshot

- **GIVEN** the replica-local snapshot does not list the requested `redeem_id` as available
- **AND** the authoritative upstream fetch reports that credit as unavailable
- **WHEN** a client calls `POST /v1/reset-credit` for that account and `redeem_id`
- **THEN** the endpoint returns 409 without calling upstream consume
- **AND** the fresh upstream snapshot replaces the replica's cached snapshot for that account

#### Scenario: Stale cached credit is re-validated after winning the claim

- **GIVEN** two replicas both cached the same reset credit as available
- **AND** replica A redeemed it while replica B waited on the cross-replica redeem claim
- **AND** replica B's cached snapshot still lists that `redeem_id` as available
- **WHEN** replica B wins the claim and processes `POST /v1/reset-credit` for that `redeem_id`
- **THEN** replica B performs the authoritative upstream fetch instead of consuming from its stale cache
- **AND** because upstream reports the credit unavailable, replica B returns 409 without sending a second upstream consume
- **AND** replica B replaces its cached snapshot with the fresh upstream snapshot

#### Scenario: Successful self-service redemption refreshes usage for immediate follow-up traffic

- **GIVEN** an eligible account has a redeemable reset credit and persisted usage/account state that still reflects a blocked window
- **WHEN** a client successfully calls `POST /v1/reset-credit` for that account
- **THEN** the redeemed account's cached reset-credit snapshot is invalidated
- **AND** codex-lb forces a usage refresh for that account before returning
- **AND** any account-selection cache entry derived from the stale usage state is invalidated when the refresh writes updated usage
- **AND** the response still returns the upstream `{code, windows_reset, redeemed_at}` success payload
