# dashboard-sidecar-management (delta)

## MODIFIED Requirements

### Requirement: OAuth usage retention across poll failures

The Claude sidecar quota poller SHALL retain the last-known per-auth OAuth
usage (`five_hour` / `seven_day` buckets) when a fresh OAuth usage fetch
fails for that auth (HTTP error, rate limit, timeout, or unreadable
credential), instead of persisting a snapshot with `oauth_usage = null`.

A successful OAuth usage fetch SHALL replace the retained data. Auths with
no previously known OAuth usage SHALL continue to report `oauth_usage = null`
until a fetch succeeds.

#### Scenario: OAuth usage fetch rate-limited

- **GIVEN** the previous quota snapshot holds OAuth usage for auth `A`
- **WHEN** the next poll's OAuth usage fetch for `A` fails with HTTP 429
- **THEN** the persisted snapshot keeps the previous `oauth_usage` for `A`
- **AND** the dashboard continues to show 5h/weekly remaining percentages

#### Scenario: OAuth usage fetch succeeds

- **GIVEN** the previous snapshot holds stale OAuth usage for auth `A`
- **WHEN** the next poll's OAuth usage fetch for `A` succeeds
- **THEN** the persisted snapshot stores the freshly fetched buckets
