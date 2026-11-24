## Why

An overload or a quota rejection from one ChatGPT account can look like a pool-wide 429 to a client. One exhausted sample can also produce a 100% usage header even when another account can serve the model. The same headers can appear on responses from providers that do not use the ChatGPT pool.

## What Changes

- Report pressure from one account as a short retry when the existing safe failover does not succeed. Do not disclose that account's usage or reset.
- Keep the structured 429 for confirmed pool exhaustion. Report the reset deadline and the window duration of the first eligible account to return.
- Do not claim 100% usage when automatic redemption can restore an eligible account or when an open stream can still fail for a reason unrelated to quota.
- Send Codex pool usage headers only for subscription-backed routes. Compute each summary over the eligible pool, including accounts with no usage sample.

## Capabilities

### Modified Capabilities

- `responses-api-compat`: scope Codex usage metadata to the route and distinguish account pressure from pool exhaustion.

## Impact

This changes public HTTP quota headers and retry guidance. It adds no setting and does not change the dashboard quota feed, account health classification, or rules for when replay is safe.
