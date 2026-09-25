## ADDED Requirements

### Requirement: API keys can answer rate limiting with HTTP 402

Each API key record MUST carry a boolean `rate_limit_as_payment_required`
field, exposed on the dashboard API as `rateLimitAsPaymentRequired`. It MUST
default to `false`, MUST be settable on creation (`POST /api/api-keys`,
optional) and on update (`PATCH /api/api-keys/{id}`), and MUST be returned on
key reads. Existing rows MUST default to `false`, so the migration changes no
behavior for keys that never set the flag.

When the flag is `true`, every HTTP response on a proxy path (`/v1/*` or
`/backend-api/*`) to a request authenticated by that key whose status would be
`429` MUST be sent with status `402` instead. The response body MUST be
unchanged, and response headers, including `Retry-After`, MUST be preserved.
Request logs MUST continue to record the original error code.

The rewrite MUST NOT apply to requests authenticated by a key without the flag,
to unauthenticated requests, to responses with any status other than `429`, or
to rejections produced before the request's API key is authenticated.

#### Scenario: Default key keeps 429

- **GIVEN** an API key with `rateLimitAsPaymentRequired: false`
- **AND** every account is rate limited
- **WHEN** the key calls `POST /v1/chat/completions`
- **THEN** the response status is 429 with error code `usage_limit_reached`
- **AND** the `Retry-After` header is present

#### Scenario: Flagged key receives 402 for pool exhaustion

- **GIVEN** an API key with `rateLimitAsPaymentRequired: true`
- **AND** every account is rate limited
- **WHEN** the key calls `POST /v1/chat/completions`
- **THEN** the response status is 402
- **AND** the body still has error code `usage_limit_reached` and the same message
- **AND** the `Retry-After` header is unchanged

#### Scenario: Flagged key receives 402 on the Responses API

- **GIVEN** an API key with `rateLimitAsPaymentRequired: true`
- **AND** every account is rate limited
- **WHEN** the key calls `POST /v1/responses`
- **THEN** the response status is 402 with error code `usage_limit_reached`

#### Scenario: Flagged key receives 402 for its own limit

- **GIVEN** an API key with `rateLimitAsPaymentRequired: true`
- **AND** the key has exceeded one of its own usage limits
- **WHEN** the key calls a proxy route
- **THEN** the response status is 402 with error code `rate_limit_exceeded`

#### Scenario: Other statuses are unchanged

- **GIVEN** an API key with `rateLimitAsPaymentRequired: true`
- **WHEN** a proxy route answers the key with a status other than 429, such as
  400 or 503
- **THEN** the status is sent unchanged

#### Scenario: Toggle round-trips through the dashboard API

- **WHEN** an administrator creates a key with `rateLimitAsPaymentRequired: true`
- **THEN** the created key returns `rateLimitAsPaymentRequired: true`
- **WHEN** the administrator PATCHes it with `rateLimitAsPaymentRequired: false`
- **THEN** the key returns `rateLimitAsPaymentRequired: false`
- **AND** a later rate-limited request authenticated by the key receives 429

#### Scenario: Unrelated edit preserves the flag

- **GIVEN** an API key with `rateLimitAsPaymentRequired: true`
- **WHEN** an administrator PATCHes only its name
- **THEN** the key still returns `rateLimitAsPaymentRequired: true`
