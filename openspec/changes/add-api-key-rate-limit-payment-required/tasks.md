## 1. Contract and persistence

- [x] 1.1 Add the `rate_limit_as_payment_required` boolean column (server default false) and a reversible migration from the current Alembic head.
- [x] 1.2 Extend API-key request/response schemas, service data, repository updates, and cache-facing mapping.

## 2. Proxy behavior

- [x] 2.1 Record the authenticated API key on the request scope in the proxy auth dependencies.
- [x] 2.2 Add an innermost pure ASGI middleware that sends 402 instead of 429 on proxy paths for flagged keys, preserving body and headers.

## 3. Dashboard

- [x] 3.1 Add a localized checkbox to the API-key create and edit dialogs and a row to the key details panel.
- [x] 3.2 Update frontend API schemas and tests.

## 4. Verification

- [x] 4.1 Route-level integration tests: pool exhaustion on chat completions and Responses for flagged and unflagged keys, per-key limit, toggle round-trip, unrelated edit keeps the flag.
- [x] 4.2 Middleware unit tests and a migration round-trip test.
- [x] 4.3 Run focused backend and frontend tests, the frontend build, lint and type checks, migration graph checks, and OpenSpec validation.
- [x] 4.4 Capture before/after dashboard screenshots.
