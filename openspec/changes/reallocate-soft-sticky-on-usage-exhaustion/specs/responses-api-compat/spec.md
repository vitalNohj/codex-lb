## ADDED Requirements

### Requirement: Pre-visible usage exhaustion must not pin a soft sticky request

When an HTTP streaming Responses request — including `/v1/chat/completions` mapped onto Responses — has no hard continuity owner, and the selected account fails before any downstream-visible output with `usage_limit_reached`, `insufficient_quota`, `quota_exceeded`, or `usage_not_included`, the proxy MUST NOT bind that retained body to the failed account as a dispatch owner. The proxy MUST exclude the failed account, reallocate any soft prompt-cache or sticky-thread mapping, and retry ordinary routing among remaining eligible accounts with the same body.

Hard previous-response, turn-state, uploaded-file, and single-account ownership MUST stay fail-closed. Mid-stream usage exhaustion after downstream-visible output MUST stay fail-closed. Brief `rate_limit_exceeded` failures outside this usage-exhaustion family MUST keep today's dispatch-owner and prompt-cache preserve-on-fallback behavior.

#### Scenario: Cursor-style first turn failovers off an exhausted sticky seat

- **GIVEN** two eligible Codex accounts and a chat-completions or Responses request with only prompt-cache stickiness
- **AND** the body is not a canonical account-neutral fresh replay because of client tool declarations
- **AND** account A returns HTTP 429 `usage_limit_reached` before any stream bytes are yielded downstream
- **WHEN** account B remains eligible
- **THEN** the proxy excludes account A, reallocates the soft sticky mapping, and completes the same body on account B
- **AND** the client does not receive the original 429

#### Scenario: Previous-response ownership still fails closed

- **GIVEN** a request that requires the previous-response owner on account A
- **AND** no verified account-neutral fresh-replay replacement body exists
- **WHEN** account A fails pre-visible with `usage_limit_reached`
- **THEN** the proxy does not dispatch the retained body to another account

#### Scenario: Mid-stream usage exhaustion stays on the settled account

- **GIVEN** account A has already yielded downstream-visible stream output
- **WHEN** a later `usage_limit_reached` failure arrives
- **THEN** the proxy surfaces that failure and MUST NOT replay the request on another account
