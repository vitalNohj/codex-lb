# quota-feed (delta)

## ADDED Requirements

### Requirement: Quota feed rows follow the API key's usage visibility

For a proxy API key, `GET /v1/quota-feed` SHALL return Codex rows only when the key's `usage_sections` include both `upstream_limits` and `account_pool_usage`, limited to its assigned accounts when account scope is enabled. It SHALL return CLIProxyAPI credential rows only when they include `upstream_limits`. `perProvider` SHALL summarize only the returned rows.

#### Scenario: Unscoped key without sections

- **GIVEN** Codex accounts and stored CLIProxyAPI quota exist
- **WHEN** an unscoped API key with empty `usage_sections` calls `GET /v1/quota-feed`
- **THEN** the response is 200 with `providers: []` and `perProvider: {}`

#### Scenario: Key with only upstream_limits

- **WHEN** an API key whose `usage_sections` are `upstream_limits` calls `GET /v1/quota-feed`
- **THEN** the response lists CLIProxyAPI credential rows and no Codex rows

### Requirement: The quota privacy setting hides the quota feed from API keys

While `hide_upstream_quota_from_api_keys` is enabled, `GET /v1/quota-feed` SHALL return no rows to a proxy API key, whatever its `usage_sections`. A verified dashboard admin SHALL keep receiving every row.

#### Scenario: Privacy setting on

- **GIVEN** `hide_upstream_quota_from_api_keys` is enabled
- **WHEN** an API key with every section calls `GET /v1/quota-feed`
- **THEN** the response has no rows
- **AND** a dashboard admin calling the same route still receives every row

### Requirement: Quota feed account keys are opaque per API key

For a proxy API key caller, each row's `accountKey` MUST be an opaque value derived with a keyed HMAC from the API key id and the router account id, using a secret every replica shares. It MUST be stable for the same key and account, MUST differ between API keys for the same account, and MUST NOT contain the router account id, a ChatGPT account id, a CLIProxyAPI auth index or file name, or an email. A dashboard admin caller MUST receive the router account ids.

#### Scenario: Two keys see different account keys

- **GIVEN** two unscoped API keys that may see Codex rows
- **WHEN** both call `GET /v1/quota-feed`
- **THEN** the same Codex account has a different `accountKey` in each response
- **AND** neither response contains the router account id

#### Scenario: Account keys are stable for one key

- **WHEN** the same API key calls `GET /v1/quota-feed` twice
- **THEN** each account has the same `accountKey` both times
